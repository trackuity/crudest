import random
import string
from typing import collections

from flask.app import Flask
from flask.json import jsonify
from marshmallow import Schema, fields

from crudest import (CreateResource, CrudResource, DeleteResource, HeadedResponse, NonListableRetrieveResource, RestApi,
                     RetrieveResource, UpdateResource, WrappedResponse, extra_args, jwt_required)

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 's3cr1t'

api = RestApi(app, title='Cat API', version='v1')

db = collections.defaultdict(dict)


class InvalidUsage(Exception):
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['msg'] = self.message
        return rv


@app.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


class IdSchema(Schema):
    id = fields.Int()


class CatSchema(IdSchema):
    name = fields.Str()
    weight = fields.Decimal(as_string=True)


class CatWhiskerSchema(IdSchema):
    cat_id = fields.Int()
    length = fields.Decimal(as_string=True)


class CatActionSchema(IdSchema):
    verb = fields.Str()


class CatSyncSchema(Schema):
    id = fields.Str()  # str, not int
    done = fields.Bool()


@api.resource('/cats/<int:cat_id>', name='Cat', schema=CatSchema)
class CatResource(CreateResource, RetrieveResource, UpdateResource, DeleteResource):

    @jwt_required
    def create(self, **kwargs):
        cat_id = max(db['Cat'].keys() or [0]) + 1
        cat = {'id': cat_id, **kwargs}
        db['Cat'][cat_id] = cat
        return cat

    @jwt_required
    @extra_args({'page': fields.Int(missing=1)})
    def list(self, page):
        links = {}
        values = list(db['Cat'].values())
        if (page + 1) * 2 <= (len(values) // 2 + 1) * 2:  # is there another page?
            links['next'] = api.url_for('Cat', page=page+1)
        # grabbing this opportunity to test headed responses!
        return HeadedResponse(
            data=values[(page-1)*2:page*2],
            links=links
        )

    @jwt_required
    def retrieve(self, cat_id):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        return db['Cat'][cat_id]

    @jwt_required
    def update(self, cat_id, **kwargs):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        updated_cat = {**db['Cat'][cat_id], **kwargs}
        db['Cat'][cat_id] = updated_cat
        return updated_cat

    @jwt_required
    def delete(self, cat_id):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        del db['Cat'][cat_id]
        # delete corresponding whiskers as well
        for cat_whisker in list(db['CatWhisker'].values()):
            if cat_whisker['cat_id'] == cat_id:
                del db['CatWhisker'][cat_whisker['id']]


@api.resource('/cats/<int:cat_id>/whiskers/<int:cat_whisker_id>', name='CatWhisker', schema=CatWhiskerSchema)
class CatWhiskerResource(CrudResource):

    @jwt_required
    def create(self, cat_id, **kwargs):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        cat_whisker_id = max(db['CatWhisker'].keys() or [0]) + 1
        cat_whisker = {'id': cat_whisker_id, 'cat_id': cat_id, **kwargs}
        db['CatWhisker'][cat_whisker_id] = cat_whisker
        return cat_whisker

    @jwt_required
    @extra_args({'page': fields.Int(missing=1)})
    def list(self, cat_id, page):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        links = {}
        values = [
            value for value in db['CatWhisker'].values()
            if value['cat_id'] == cat_id
        ]
        if (page + 1) * 3 <= (len(values) // 3 + 1) * 3:  # is there another page?
            links['next'] = api.url_for('CatWhisker', cat_id=cat_id, page=page+1)
        # grabbing this opportunity to test wrapped responses!
        return WrappedResponse(
            data=values[(page-1)*3:page*3],
            links=links
        )

    @jwt_required
    def retrieve(self, cat_id, cat_whisker_id):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        if cat_whisker_id not in db['CatWhisker']:
            raise InvalidUsage('Whisker not found.', status_code=404)
        return db['CatWhisker'][cat_whisker_id]

    @jwt_required
    def update(self, cat_id, cat_whisker_id, **kwargs):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        if cat_whisker_id not in db['CatWhisker']:
            raise InvalidUsage('Whisker not found.', status_code=404)
        updated_cat_whisker = {**db['CatWhisker'][cat_whisker_id], **kwargs}
        db['CatWhisker'][cat_whisker_id] = updated_cat_whisker
        return updated_cat_whisker

    @jwt_required
    def delete(self, cat_id, cat_whisker_id):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        if cat_whisker_id not in db['CatWhisker']:
            raise InvalidUsage('Whisker not found.', status_code=404)
        del db['CatWhisker'][cat_whisker_id]


@api.resource('/cats/<int:cat_id>/actions/<int:cat_action_id>', name='CatAction', schema=CatActionSchema)
class CatActionResource(CreateResource, UpdateResource):

    @jwt_required
    def create(self, cat_id, verb):
        return self.update(cat_id, 1, verb)

    @jwt_required
    def update(self, cat_id, cat_action_id, verb):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        cat_name = db['Cat'][cat_id]['name']
        return WrappedResponse(
            data={
                'id': 1,
                'result': f'The cat named {cat_name} {verb}ed.'
            },
            links=dict(
                self=api.url_for('CatAction', cat_id=cat_id, cat_action_id=1)
            )
        )


@api.resource('/cats/<int:cat_id>/syncs/<cat_sync_id>', name='CatSync', schema=CatSyncSchema)
class CatSyncResource(CreateResource, NonListableRetrieveResource):

    @jwt_required
    def create(self, cat_id):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        cat_sync_id = ''.join([random.choice(string.ascii_letters + string.digits) for n in range(32)])
        cat_sync = {'id': cat_sync_id, 'done': False}
        db['CatSync'][cat_sync_id] = cat_sync
        return cat_sync

    @jwt_required
    def retrieve(self, cat_id, cat_sync_id):
        if cat_id not in db['Cat']:
            raise InvalidUsage('Cat not found.', status_code=404)
        cat_sync = db['CatSync'].get(cat_sync_id)
        if cat_sync is None:
            raise InvalidUsage('Cat sync not found.', status_code=404)
        return cat_sync
