import flask_jwt_extended
import functools
import re

from abc import ABCMeta, abstractmethod
from apispec import APISpec
from apispec.ext.marshmallow import swagger
from flask import request, jsonify
from flask.views import MethodView
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_optional, \
    fresh_jwt_required, jwt_refresh_token_required
from flask_swagger_ui import get_swaggerui_blueprint
from webargs import fields
from webargs.flaskparser import parser, use_kwargs


__all__ = [
    'Resource',
    'CreateResource',
    'RetrieveResource',
    'UpdateResource',
    'DeleteResource',
    'CrudResource',
    'RestApi',
    'fields',
    'extra_args',
    'create_access_token',
    'get_jwt_identity',
    'jwt_required',
    'jwt_optional',
    'fresh_jwt_required',
    'jwt_refresh_token_required',
]


class Resource(object):
    __metaclass__ = ABCMeta


class CreateResource(Resource):

    @abstractmethod
    def create(self, *args, **kwargs):
        raise NotImplementedError()


class RetrieveResource(Resource):

    @abstractmethod
    def list(self, *args):
        raise NotImplementedError()

    @abstractmethod
    def retrieve(self, *args):
        raise NotImplementedError()


class UpdateResource(Resource):

    @abstractmethod
    def update(self, resource_id):
        raise NotImplementedError()


class DeleteResource(Resource):

    @abstractmethod
    def delete(self, resource_id):
        raise NotImplementedError()


class CrudResource(CreateResource, RetrieveResource, UpdateResource, DeleteResource):
    pass


class RestView(MethodView):

    def __init__(self, schema_cls, resource, num_ids=1):
        super(MethodView, self).__init__()
        self.schema_cls = schema_cls
        self.resource = resource
        self.num_ids = num_ids

    def post(self, **kwargs):
        kwargs.update(parser.parse(self.schema_cls(strict=True), request))
        result = self.resource.create(**kwargs)
        return jsonify(self.schema_cls().dump(result).data), 201

    def get(self, **kwargs):
        if len(kwargs) < self.num_ids:
            result = self.resource.list(**kwargs)
            return jsonify(self.schema_cls(many=True).dump(result).data)
        else:
            result = self.resource.retrieve(**kwargs)
            return jsonify(self.schema_cls().dump(result).data)

    def put(self, **kwargs):
        kwargs.update(parser.parse(self.schema_cls(), request))
        result = self.resource.update(**kwargs)
        return jsonify(self.schema_cls().dump(result).data)

    def delete(self, **kwargs):
        self.resource.delete(**kwargs)
        return '', 204


class RestApi(object):

    RE_URL = re.compile(r'<(?:[^:<>]+:)?([^<>]+)>')

    def __init__(self, app, title, version='v1', spec_path='/spec', docs_path='/docs'):
        self.app = app
        self.spec = spec = APISpec(
            title=title,
            version=version,
            plugins=['apispec.ext.marshmallow'],
        )
        self.jwt = JWTManager(app)

        spec.options['securityDefinitions'] = {
            'jwt_auth': {
                'type': 'apiKey',
                'in': 'header',
                'description': 'This is the closest approximation OpenAPI 2.0 has for JWT auth. '
                               'Use a token prefixed with "Bearer " as header value in swagger-ui.'
            }
        }
        spec.options['security'] = {
            'jwt_auth': []
        }

        @app.route(spec_path)
        def get_spec():
            return jsonify(spec.to_dict())

        swaggerui_blueprint = get_swaggerui_blueprint(docs_path, spec_path)
        app.register_blueprint(swaggerui_blueprint, url_prefix=docs_path)

    def resource(self, path, name, schema):
        self.spec.definition(name, schema=schema)

        def decorator(cls):
            base_path = '/'.join(path.split('/')[:-1])
            view = RestView.as_view(cls.__name__.lower(), schema, cls(), len(path[1:].split('/')) / 2)
            if issubclass(cls, CreateResource):
                self.add_path(base_path, view, method='POST', tag=name,
                              input_schema=schema, output_schema=schema,
                              extra_args=getattr(cls.create, '__extra_args__', None),
                              auth_required=getattr(cls.create, '__auth_required__', False),
                              status_code=201, description=cls.create.__doc__)
            if issubclass(cls, RetrieveResource):
                self.add_path(base_path, view, method='GET', tag=name,
                              output_schema=schema(many=True),
                              extra_args=getattr(cls.list, '__extra_args__', None),
                              auth_required=getattr(cls.list, '__auth_required__', False),
                              description=cls.list.__doc__)
                self.add_path(path, view, method='GET', tag=name,
                              output_schema=schema,
                              extra_args=getattr(cls.retrieve, '__extra_args__', None),
                              auth_required=getattr(cls.retrieve, '__auth_required__', False),
                              description=cls.retrieve.__doc__)
            if issubclass(cls, UpdateResource):
                self.add_path(path, view, method='PUT', tag=name,
                              input_schema=schema, output_schema=schema,
                              extra_args=getattr(cls.update, '__extra_args__', None),
                              auth_required=getattr(cls.update, '__auth_required__', False),
                              description=cls.update.__doc__)
                self.app.add_url_rule(path, view_func=view, methods=['PUT'])
            if issubclass(cls, DeleteResource):
                self.add_path(path, view, method='DELETE', tag=name,
                              extra_args=getattr(cls.delete, '__extra_args__', None),
                              auth_required=getattr(cls.delete, '__auth_required__', False),
                              status_code=204, description=cls.delete.__doc__)
            return cls

        return decorator

    def add_path(self, path, view, method, tag,
                 input_schema=None, output_schema=None, extra_args=None, auth_required=False,
                 status_code='default', description=''):
        swagger_path = self.RE_URL.sub(r'{\1}', path)
        self.app.add_url_rule(path, view_func=view, methods=[method])
        parameters = []
        if input_schema:
            parameters.extend(swagger.schema2parameters(input_schema))
        if extra_args:
            parameters.extend(swagger.fields2parameters(extra_args))
        self.spec.add_path(swagger_path, {
            method.lower(): {
                'description': description,
                'parameters': [merge_recursive(parameters)],
                'responses': {
                    status_code: {'schema': output_schema} if output_schema else {}
                },
                'tags': [tag],
                'security': [{'jwt_auth': []}] if auth_required else []
            }
        })


def extra_args(args):

    def decorator(func):
        if getattr(func, '__extra_args__', None) is None:
            func.__extra_args__ = {}
        func.__extra_args__.update(args)
        return use_kwargs(args)(func)

    return decorator


def jwt_required(func):
    if getattr(func, '__auth_required__', None) is None:
        func.__auth_required__ = True
    return flask_jwt_extended.jwt_required(func)


def merge_recursive(values):
    return functools.reduce(_merge_recursive, values, {})


def _merge_recursive(child, parent):
    if isinstance(child, dict) or isinstance(parent, dict):
        child = child or {}
        parent = parent or {}
        keys = set(child.keys()).union(parent.keys())
        return {
            key: _merge_recursive(child.get(key), parent.get(key))
            for key in keys
        }
    return child if child is not None else parent
