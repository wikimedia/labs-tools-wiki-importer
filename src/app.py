#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import yaml
from flask import redirect, request, jsonify, render_template, url_for, \
    make_response, flash, session
from flask import Flask
import requests
import subprocess
from flask_jsonlocale import Locales
from flask_mwoauth import MWOAuth
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from celery import Celery
from requests_oauthlib import OAuth1
import shutil

app = Flask(__name__, static_folder='../static')

db = SQLAlchemy(app)
migrate = Migrate(app, db)

ALLOWED_GROUPS = ['new-wikis-importer', 'steward']
useragent = 'WikiImporter (tools.wiki-importer@tools.wmflabs.org)'

# Load configuration from YAML file
__dir__ = os.path.dirname(__file__)
app.config.update(
    yaml.safe_load(open(os.path.join(__dir__, os.environ.get(
        'FLASK_CONFIG_FILE', 'config.yaml')))))

# Add databse credentials to config
if app.config.get('DBCONFIG_FILE') is not None:
    app.config['SQLALCHEMY_DATABASE_URI'] = app.config.get('DB_URI') + '?read_default_file={cfile}'.format(cfile=app.config.get('DBCONFIG_FILE'))

locales = Locales(app)
_ = locales.get_message

mwoauth = MWOAuth(
    consumer_key=app.config.get('CONSUMER_KEY'),
    consumer_secret=app.config.get('CONSUMER_SECRET'),
    base_url=app.config.get('OAUTH_MWURI'),
    return_json=True
)
app.register_blueprint(mwoauth.bp)

def make_celery():
    celery = Celery(
        app.import_name,
        backend=app.config.get('CELERY_RESULT_BACKEND'),
        broker=app.config.get('CELERY_BROKER_URL')
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        queue = 'urbanecm_wiki_importer'

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery

celery = make_celery()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    token_key = db.Column(db.String(255))
    token_secret = db.Column(db.String(255))

class Wiki(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    dbname = db.Column(db.String(255))
    prefix = db.Column(db.String(255))
    is_imported = db.Column(db.Boolean, default=False)
    import_started = db.Column(db.Boolean, default=False)

    def __str__(self):
        return self.dbname
    
    def get_pages(self, namespace=None):
        payload = {
            "action": "query",
            "format": "json",
            "list": "allpages",
            "aplimit": "max",
            "apprefix": "%s/" % self.prefix
        }
        res = []
        while True:
            data = mwoauth.request(payload, app.config.get('INCUBATOR_MWURI'))
            pages = data.get('query').get('allpages')
            for page in pages:
                res.append(page.get('title'))
            
            if data.get('continue'):
                for param in data.get('continue'):
                    payload[param] = data['continue'].get(param)
            else:
                break
        return res

    @property
    def path(self):
        path = self.raw_path
        if not os.path.exists(path):
            os.mkdir(path)
        return os.path.abspath(path)

    @property
    def raw_path(self):
        return os.path.join(app.config.get('TMP_DIR'), self.dbname)


def logged():
    return mwoauth.get_current_user() is not None

def get_user():
    return User.query.filter_by(
        username=mwoauth.get_current_user()
    ).first()

def mw_request(data, url=None, user=None):
    if url is None:
        api_url = mwoauth.api_url + "/api.php"
    else:
        api_url = url
    if user is None:
        access_token = session.get('mwoauth_access_token', {})
        request_token_secret = access_token.get('secret').decode('utf-8')
        request_token_key = access_token.get('key').decode('utf-8')
    else:
        request_token_secret = user.token_secret
        request_token_key = user.token_key
    auth = OAuth1(app.config.get('CONSUMER_KEY'), app.config.get('CONSUMER_SECRET'), request_token_key, request_token_secret)
    data['format'] = 'json'
    return requests.post('https://meta.wikimedia.org/w/api.php', data=data, auth=auth, headers={'User-Agent': useragent})

@app.context_processor
def inject_base_variables():
    return {
        "logged": logged(),
        "username": mwoauth.get_current_user(),
    }

@app.before_request
def ensure_login():
    if request.path != '/login' and request.path != '/oauth-callback':
        if not logged():
            return render_template('login.html')

@app.before_request
def db_init_user():
    if logged():
        user = get_user()
        access_token = session.get('mwoauth_access_token', {})
        request_token_secret = access_token.get('secret').decode('utf-8')
        request_token_key = access_token.get('key').decode('utf-8')
        if user is None:
            user = User(
                username=mwoauth.get_current_user(),
                token_key=request_token_key,
                token_secret=request_token_key,
            )
            db.session.add(user)
            db.session.commit()
        else:
            user.token_key = request_token_key
            user.token_secret = request_token_secret
            if not user.is_active:
                return render_template('permission_denied.html'), 403
            
            db.session.commit()

@app.before_request
def ensure_privileges():
    if request.path == '/login' or request.path == '/oauth-callback' or request.path == '/logout':
        return

    if logged():
        data = mwoauth.request({
            "action": "query",
            "format": "json",
            "meta": "globaluserinfo",
            "guiprop": "groups"
        })
        groups = data.get('query', {}).get('globaluserinfo', {}).get('groups')
        for group in ALLOWED_GROUPS:
            if group in groups:
                return
        return render_template('permission_denied.html')

@app.route('/')
def index():
    wikis = Wiki.query.filter_by(is_imported=False)
    return render_template('index.html', wikis=wikis)

@app.route('/new-wiki', methods=['POST'])
def new_wiki():
    w = Wiki(dbname=request.form.get('dbname'), prefix=request.form.get('prefix'))
    db.session.add(w)
    db.session.commit()
    return redirect(url_for('index'))


@app.route('/wiki/<path:dbname>')
def wiki_action(dbname):
    wiki = Wiki.query.filter_by(dbname=dbname)[0]
    return render_template('wiki.html', wiki=wiki)

@app.route('/test.json')
def test():
    return jsonify(mw_request({
        'action': 'query',
        'meta': 'globaluserinfo'
    }).json())

if __name__ == "__main__":
    app.run(debug=True, threaded=True)
