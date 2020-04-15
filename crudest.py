import functools
import re
from abc import ABCMeta, abstractmethod

import flask_jwt_extended
from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from flask import jsonify, request
from flask.helpers import make_response, url_for
from flask.views import MethodView
from flask_jwt_extended import (JWTManager, create_access_token,
                                create_refresh_token, get_jti, get_jwt_claims,
                                get_jwt_identity)
from flask_swagger_ui import get_swaggerui_blueprint
from webargs import fields
from webargs.flaskparser import parser, use_kwargs

__all__ = [
    'Resource',
    'CreateResource',
    'NonListableRetrieveResource',
    'RetrieveResource',
    'UpdateResource',
    'DeleteResource',
    'CrudResource',
    'RestApi',
    'Response',
    'HeadedResponse',
    'WrappedResponse',
    'fields',
    'extra_args',
    'create_access_token',
    'create_refresh_token',
    'get_jwt_identity',
    'get_jwt_claims',
    'get_jti',
    'basic_auth_required',
    'jwt_required',
    'jwt_optional',
    'fresh_jwt_required',
    'jwt_refresh_token_required',
]


class Resource(metaclass=ABCMeta):
    pass


class CreateResource(Resource):

    @abstractmethod
    def create(self, *args, **kwargs):
        raise NotImplementedError()


class NonListableRetrieveResource(Resource):

    @abstractmethod
    def retrieve(self, *args, **kwargs):
        raise NotImplementedError()


class RetrieveResource(NonListableRetrieveResource):

    @abstractmethod
    def list(self, *args, **kwargs):
        raise NotImplementedError()


class UpdateResource(Resource):

    @abstractmethod
    def update(self, *args, **kwargs):
        raise NotImplementedError()


class DeleteResource(Resource):

    @abstractmethod
    def delete(self, *args, **kwargs):
        raise NotImplementedError()


class CrudResource(CreateResource, RetrieveResource, UpdateResource, DeleteResource):
    pass


class Response:
    """
    Response objects can be used to pass metadata in your API responses. In 
    particular, they allow the passing of relevant link relations. Some of these
    links get added automatically, but you can also add more yourself. The link
    names should be taken from the standard IANA Link Relation Registry:
    
    https://www.iana.org/assignments/link-relations/link-relations.xhtml
    """

    def __init__(self, data, links=None):
        self._data = data
        self._links = links if links is not None else {}

    def dump_data(self, schema_cls, many=False):
        return schema_cls(many=many).dump(self._data)
    
    def extend_links(self, base_links):
        if base_links is None:
            return self._links
        else:
            return {**base_links, **self._links}

    def generate(self, schema_cls, many, base_links=None):
        """
        The base implementation simply generates JSON, ignoring the links.
        """
        return jsonify(self.dump_data(schema_cls, many=many))


class HeadedResponse(Response):
    """
    Adds the links metadata to the response via the HTTP Link header and allows
    any other given headers to be added as well.
    """

    def __init__(self, data, links=None, headers=None):
        super().__init__(data, links)
        self._headers = headers

    def generate(self, schema_cls, many, base_links=None):
        response = make_response(super().generate(schema_cls, many=many))
        response.headers['Link'] = ', '.join(
            f'<{u}>; rel="{n}"'
            for (n, u) in self.extend_links(base_links).items()
        )
        if self._headers is not None:
            for key, value in self._headers.items():
                response.headers[key] = value
        return response


class WrappedResponse(Response):
    """
    Wraps the actual response content under a top-level 'data' member in the
    generated JSON, so that other metadata can be added to the response under
    different top-level members.
    """

    def __init__(self, data, links=None, **kwargs):
        super().__init__(data, links)
        self._kwargs = kwargs
    
    def generate(self, schema_cls, many, base_links=None):
        return jsonify(
            data=self.dump_data(schema_cls, many=many),
            links=self.extend_links(base_links),
            **self._kwargs
        )


class RestView(MethodView):

    @staticmethod
    def _extract_parent_ids(resource, kwargs):
        return {p: kwargs[p] for p in resource.id_params[:-1]}

    def __init__(self, schema_cls, resource, num_ids=1):
        super().__init__()
        self.schema_cls = schema_cls
        self.resource = resource
        self.num_ids = num_ids

    def post(self, **kwargs):
        parent_ids = self._extract_parent_ids(self.resource, kwargs)
        kwargs.update(parser.parse(
            self.schema_cls(),
            request,
            location='json_or_form'
        ))
        response = self.resource.create(**kwargs)
        if not isinstance(response, Response):
            response = Response(data=response)
        return response.generate(self.schema_cls, many=False, base_links={
            'collection': url_for(self.resource.name, _external=True, **parent_ids)
        }), 201

    def get(self, **kwargs):
        parent_ids = self._extract_parent_ids(self.resource, kwargs)
        if len(kwargs) < self.num_ids:
            response = self.resource.list(**kwargs)
            if not isinstance(response, Response):
                response = Response(data=response)
            return response.generate(self.schema_cls, many=True, base_links={
                'self': url_for(self.resource.name, _external=True, **parent_ids)
            })
        else:
            response = self.resource.retrieve(**kwargs)
            if not isinstance(response, Response):
                response = Response(data=response)
            return response.generate(self.schema_cls, many=False, base_links={
                'self': url_for(
                    self.resource.name,
                    _external=True,
                    **{**parent_ids, **kwargs}
                ),
                'collection': url_for(
                    self.resource.name,
                    _external=True,
                    **parent_ids
                )
            })

    def put(self, **kwargs):
        parent_ids = self._extract_parent_ids(self.resource, kwargs)
        kwargs.update(parser.parse(
            self.schema_cls(partial=True),
            request,
            location='json_or_form'
        ))
        response = self.resource.update(**kwargs)
        if not isinstance(response, Response):
            response = Response(data=response)
        return response.generate(self.schema_cls, many=False, base_links={
            'collection': url_for(self.resource.name, _external=True, **parent_ids)
        })

    def delete(self, **kwargs):
        self.resource.delete(**kwargs)
        return '', 204


class RestApi:

    RE_URL = re.compile(r'<(?:[^:<>]+:)?([^<>]+)>')

    def __init__(self, app, title, version='v1', spec_path='/spec', docs_path='/docs'):
        self.app = app
        self.resource_methods = {}

        marshmallow_plugin = MarshmallowPlugin()
        self.spec = spec = APISpec(
            title=title,
            version=version,
            openapi_version="3.0.2",
            plugins=[marshmallow_plugin],
        )
        self.openapi = marshmallow_plugin.converter  # openapi converter from marshmallow plugin

        self.jwt = JWTManager(app)
        self.token_in_blacklist_checker = self.jwt.token_in_blacklist_loader  # shortcut to blacklisting decorator
        self.token_claims_loader = self.jwt.user_claims_loader  # shortcut to user claims decorator

        spec.components.security_scheme('basic_http', {
            'type': 'http',
            'scheme': 'basic'
        })
        spec.components.security_scheme('jwt_access_token', {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT'
        })
        spec.components.security_scheme('jwt_refresh_token', {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT'
        })

        @app.route(spec_path)
        def get_spec():
            return jsonify(spec.to_dict())

        swaggerui_blueprint = get_swaggerui_blueprint(docs_path, spec_path)
        app.register_blueprint(swaggerui_blueprint, url_prefix=docs_path)

    def resource(self, path, name, schema):
        self.spec.components.schema(name, schema=schema)

        def decorator(cls):
            cls.name = name
            cls.id_params = self.RE_URL.findall(path)

            base_path = '/'.join(path.split('/')[:-1])
            view = RestView.as_view(name, schema, cls(), len(cls.id_params))
            if issubclass(cls, CreateResource):
                self.add_path(base_path, view, method='POST',
                              tag=name, id_params=cls.id_params[:-1],
                              input_schema=schema, output_schema=schema,
                              extra_args=getattr(cls.create, '__extra_args__', None),
                              auth_required=getattr(cls.create, '__auth_required__', None),
                              status_code=201, description=cls.create.__doc__)
            if issubclass(cls, RetrieveResource):
                self.add_path(base_path, view, method='GET',
                              tag=name, id_params=cls.id_params[:-1],
                              output_schema=schema(many=True),
                              extra_args=getattr(cls.list, '__extra_args__', None),
                              auth_required=getattr(cls.list, '__auth_required__', None),
                              description=cls.list.__doc__)
            if issubclass(cls, NonListableRetrieveResource):
                self.add_path(path, view, method='GET',
                              tag=name, id_params=cls.id_params,
                              output_schema=schema,
                              extra_args=getattr(cls.retrieve, '__extra_args__', None),
                              auth_required=getattr(cls.retrieve, '__auth_required__', None),
                              description=cls.retrieve.__doc__)
            if issubclass(cls, UpdateResource):
                self.add_path(path, view, method='PUT',
                              tag=name, id_params=cls.id_params,
                              input_schema=schema, output_schema=schema,
                              extra_args=getattr(cls.update, '__extra_args__', None),
                              auth_required=getattr(cls.update, '__auth_required__', None),
                              description=cls.update.__doc__)
                self.app.add_url_rule(path, view_func=view, methods=['PUT'])
            if issubclass(cls, DeleteResource):
                self.add_path(path, view, method='DELETE',
                              tag=name, id_params=cls.id_params,
                              extra_args=getattr(cls.delete, '__extra_args__', None),
                              auth_required=getattr(cls.delete, '__auth_required__', None),
                              status_code=204, description=cls.delete.__doc__)

            # keep track of methods
            self.resource_methods[name] = next(
                r.methods for r in self.app.url_map.iter_rules() if r.endpoint == name
            )
                            
            return cls

        return decorator

    def add_path(self, path, view, method, tag, id_params=None,
                 input_schema=None, output_schema=None, extra_args=None, auth_required=None,
                 status_code='default', description=''):
        swagger_path = self.RE_URL.sub(r'{\1}', path)
        self.app.add_url_rule(path, view_func=view, methods=[method])

        parameters = [{'name': id_param, 'in': 'path'} for id_param in id_params]
        if extra_args:
            parameters.extend(self.openapi.fields2parameters(extra_args, default_in='query'))

        request_body = {}
        if input_schema:
            request_body['requestBody'] = {
                'content': {
                    'application/json': {
                        'schema': self.openapi.schema2jsonschema(input_schema)
                    }
                }
            }

        self.spec.path(swagger_path, operations={
            method.lower(): {
                'description': description,
                'parameters': parameters,
                'responses': {
                    status_code: {'schema': output_schema} if output_schema else {}
                },
                'tags': [tag],
                'security': [{auth_required: []}] if auth_required else [],
                **request_body
            }
        })

    def url_for(self, resource_name, _method=None, _external=True, **kwargs):
        if _method is None:
            methods = self.resource_methods[resource_name]
            for desired_method in ('GET', 'PUT', 'DELETE', 'POST'):
                if desired_method in methods:
                    _method = desired_method
                    break
        return url_for(resource_name, _method=_method, _external=_external, **kwargs)


def extra_args(args):

    def decorator(func):
        if getattr(func, '__extra_args__', None) is None:
            func.__extra_args__ = {}
        func.__extra_args__.update(args)
        return use_kwargs(args, location='query')(func)

    return decorator


def basic_auth_required(func):
    func.__auth_required__ = 'basic_http'
    return func


def jwt_required(func):
    func.__auth_required__ = 'jwt_access_token'
    return flask_jwt_extended.jwt_required(func)


def jwt_optional(func):
    func.__auth_required__ = 'jwt_access_token'
    return flask_jwt_extended.jwt_optional(func)


def fresh_jwt_required(func):
    func.__auth_required__ = 'jwt_access_token'
    return flask_jwt_extended.fresh_jwt_required(func)


def jwt_refresh_token_required(func):
    func.__auth_required__ = 'jwt_refresh_token'
    return flask_jwt_extended.jwt_refresh_token_required(func)
