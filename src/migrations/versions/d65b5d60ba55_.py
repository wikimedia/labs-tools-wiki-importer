"""empty message

Revision ID: d65b5d60ba55
Revises: 
Create Date: 2020-09-03 10:30:26.793972

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd65b5d60ba55'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('wiki',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dbname', sa.String(length=255), nullable=True),
    sa.Column('prefix', sa.String(length=255), nullable=True),
    sa.Column('is_split', sa.Boolean(), nullable=True),
    sa.Column('is_imported', sa.Boolean(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('wiki')
    # ### end Alembic commands ###
