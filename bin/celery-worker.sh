#!/bin/bash

source ~/venv/bin/activate
cd ~/src
celery worker -A app.celery -Q urbanecm_wiki_importer --loglevel=info
