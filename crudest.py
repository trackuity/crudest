import collections
import re
from abc import ABC, abstractmethod

import flask_jwt_extended
from apispec import APISpec
from apispec.ext.marshmallow import MarshmallowPlugin
from flask import jsonify, request, Blueprint
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
    'ListResource',
    'NonListableRetrieveResource',
    'RetrieveResource',
    'UpdateResource',
    'DeleteResource',
    'CrudResource',
    'RestApi',
    'RestApiBlueprint',
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


class Resource(ABC):
    pass


class CreateResource(Resource):

    @abstractmethod
    def create(self, *args, **kwargs):
        raise NotImplementedError()


class ListResource(Resource):

    @abstractmethod
    def list(self, *args, **kwargs):
        raise NotImplementedError()


class NonListableRetrieveResource(Resource):

    @abstractmethod
    def retrieve(self, *args, **kwargs):
        raise NotImplementedError()


class RetrieveResource(NonListableRetrieveResource, ListResource, ABC):
    pass


class ReplaceResource(Resource):

    @abstractmethod
    def replace(self, *args, **kwargs):
        raise NotImplementedError()


class UpdateResource(ReplaceResource):

    def replace(self, *args, **kwargs):
        return self.update(*args, **kwargs)

    @abstractmethod
    def update(self, *args, **kwargs):
        raise NotImplementedError()


class DeleteResource(Resource):

    @abstractmethod
    def delete(self, *args, **kwargs):
        raise NotImplementedError()


class CrudResource(CreateResource, RetrieveResource, UpdateResource, DeleteResource, ABC):
    pass


class Response:
    """
    Response objects can be used to pass metadata in your API responses. In 
    particular, they allow the passing of relevant link relations. Some of these
    links get added automatically, but you can also add more yourself. The link
    names should be taken from the standard IANA Link Relation Registry:
    
    https://www.iana.org/assignments/link-relations/link-relations.xhtml
    """

    def __init__(self, data, status_code=None, links=None):
        self._data = data
        self._status_code = status_code
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

    def get_status_code(self, default=None):
        return self._status_code or default


class HeadedResponse(Response):
    """
    Adds the links metadata to the response via the HTTP Link header and allows
    any other given headers to be added as well.
    """

    CORS_SAFELISTED_HEADERS = {
        'Cache-Control',
        'Content-Language',
        'Content-Length',
        'Content-Type',
        'Expires',
        'Last-Modified',
        'Pragma'
    }

    def __init__(self, data, status_code=None, links=None, headers=None):
        super().__init__(data, status_code, links)
        self._headers = headers

    def generate(self, schema_cls, many, base_links=None):
        response = make_response(super().generate(schema_cls, many=many))
        link_header = ', '.join(
            f'<{u}>; rel="{n}"'
            for (n, u) in self.extend_links(base_links).items()
        )
        added_headers = set()
        if link_header:
            response.headers['Link'] = link_header
            added_headers.add('Link')
        if self._headers is not None:
            for key, value in self._headers.items():
                response.headers[key] = value
                added_headers.add(key)
        expose_headers = added_headers - self.CORS_SAFELISTED_HEADERS
        if expose_headers:
            response.headers['Access-Control-Expose-Headers'] = ', '.join(expose_headers)
        return response


class WrappedResponse(Response):
    """
    Wraps the actual response content under a top-level 'data' member in the
    generated JSON, so that other metadata can be added to the response under
    different top-level members.
    """

    def __init__(self, data, status_code=None, links=None, data_key='data', **kwargs):
        super().__init__(data, status_code, links)
        self._data_key = data_key
        self._kwargs = kwargs
    
    def generate(self, schema_cls, many, base_links=None):
        return jsonify(
            links=self.extend_links(base_links),
            **{
                self._data_key: self.dump_data(schema_cls, many=many),
                **self._kwargs
            }
        )


class RestView(MethodView):

    @staticmethod
    def _extract_parent_ids(resource, kwargs):
        return {p.name: kwargs[p.name] for p in resource.id_params[:-1]}

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
            'collection': url_for('.' + self.resource.name, _external=True, **parent_ids)
        }), response.get_status_code(default=201)

    def get(self, **kwargs):
        parent_ids = self._extract_parent_ids(self.resource, kwargs)
        if len(kwargs) < self.num_ids:
            response = self.resource.list(**kwargs)
            if not isinstance(response, Response):
                response = Response(data=response)
            return response.generate(self.schema_cls, many=True, base_links={
                'self': url_for('.' + self.resource.name, _external=True, **parent_ids)
            }), response.get_status_code(default=200)
        else:
            response = self.resource.retrieve(**kwargs)
            if not isinstance(response, Response):
                response = Response(data=response)
            return response.generate(self.schema_cls, many=False, base_links={
                'self': url_for(
                    '.' + self.resource.name,
                    _external=True,
                    **{**parent_ids, **kwargs}
                ),
                'collection': url_for(
                    '.' + self.resource.name,
                    _external=True,
                    **parent_ids
                )
            }), response.get_status_code(default=200)

    def put(self, **kwargs):
        parent_ids = self._extract_parent_ids(self.resource, kwargs)
        kwargs.update(parser.parse(
            self.schema_cls(),
            request,
            location='json_or_form'
        ))
        response = self.resource.replace(**kwargs)
        if not isinstance(response, Response):
            response = Response(data=response)
        return response.generate(self.schema_cls, many=False, base_links={
            'collection': url_for('.' + self.resource.name, _external=True, **parent_ids)
        }), response.get_status_code(default=200)

    def patch(self, **kwargs):
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
            'collection': url_for('.' + self.resource.name, _external=True, **parent_ids)
        }), response.get_status_code(default=200)

    def delete(self, **kwargs):
        self.resource.delete(**kwargs)
        return '', 204


class RestApi:

    URL_CONVERTER_TO_TYPE = {
        'string': 'string',
        'int': 'integer',
        'float': 'number',
        'path': 'string',
    }

    RE_URL = re.compile(r'<(?:([^:<>]+):)?([^<>]+)>')

    IdParam = collections.namedtuple('IdParam', ['type', 'name'])

    def __init__(
        self, app, title, version='v1', spec_path='/spec', docs_path='/docs', servers=None,
        security_schemes=None, default_security_scheme=None
    ):
        self.app = app
        self.resource_methods = collections.defaultdict(set)

        marshmallow_plugin = MarshmallowPlugin()
        self.spec = spec = APISpec(
            title=title,
            version=version,
            openapi_version="3.0.2",
            plugins=[marshmallow_plugin],
        )
        self.openapi = marshmallow_plugin.converter  # openapi converter from marshmallow plugin

        self.jwt = JWTManager()
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

        if security_schemes is not None:
            for name, scheme in security_schemes.items():
                spec.components.security_scheme(name, scheme)

        self.default_security_scheme = default_security_scheme

        if not isinstance(app, Blueprint):
            self.init_app(app, spec_path, docs_path, servers=servers)  # needs to be called separately when blueprint

    def init_app(self, app, spec_path='/spec', docs_path='/docs', docs_blueprint_name='swagger_ui', servers=None):
        """
        This needs to be called with the main app as argument when the api is defined on a flask blueprint.
        """
        @app.route(spec_path)
        def get_spec():
            spec_dict = self.spec.to_dict()
            return jsonify({'servers': servers, **spec_dict} if servers is not None else spec_dict)

        self.jwt.init_app(app)
        swaggerui_blueprint = get_swaggerui_blueprint(
            docs_path, spec_path, blueprint_name=docs_blueprint_name
        )
        app.register_blueprint(swaggerui_blueprint, url_prefix=docs_path)

    def resource(self, path, name, schema):
        self.spec.components.schema(name, schema=schema)

        def decorator(cls):
            return self.add_resource(cls, path, name, schema)            

        return decorator

    def add_resource(self, cls, path, name, schema):
        cls.name = name
        cls.id_params = [
            self.IdParam(self.URL_CONVERTER_TO_TYPE.get(type_, 'string'), name)
            for (type_, name) in self.RE_URL.findall(path)
        ]

        base_path = '/'.join(path.split('/')[:-1])
        view = RestView.as_view(name, schema, cls(), len(cls.id_params))
        if issubclass(cls, CreateResource):
            self.resource_methods[name].add('POST')
            self.add_path(base_path, view, method='POST',
                            tag=name, id_params=cls.id_params[:-1],
                            input_schema=schema(), output_schema=schema(),
                            extra_args=getattr(cls.create, '__extra_args__', None),
                            auth_required=getattr(cls.create, '__auth_required__', None),
                            status_code=201, description=cls.create.__doc__)
        if issubclass(cls, ListResource):
            self.resource_methods[name].add('GET')
            self.add_path(base_path, view, method='GET',
                            tag=name, id_params=cls.id_params[:-1],
                            output_schema=schema(many=True),
                            extra_args=getattr(cls.list, '__extra_args__', None),
                            auth_required=getattr(cls.list, '__auth_required__', None),
                            description=cls.list.__doc__)
        if issubclass(cls, NonListableRetrieveResource):
            self.resource_methods[name].add('GET')
            self.add_path(path, view, method='GET',
                            tag=name, id_params=cls.id_params,
                            output_schema=schema(),
                            extra_args=getattr(cls.retrieve, '__extra_args__', None),
                            auth_required=getattr(cls.retrieve, '__auth_required__', None),
                            description=cls.retrieve.__doc__)
        if issubclass(cls, ReplaceResource):
            self.resource_methods[name].add('PUT')
            self.add_path(path, view, method='PUT',
                            tag=name, id_params=cls.id_params,
                            input_schema=schema(), output_schema=schema(),
                            extra_args=getattr(cls.update, '__extra_args__', None),
                            auth_required=getattr(cls.update, '__auth_required__', None),
                            description=cls.update.__doc__)
            self.app.add_url_rule(path, view_func=view, methods=['PUT'])
        if issubclass(cls, UpdateResource):
            self.resource_methods[name].add('PATCH')
            self.add_path(path, view, method='PATCH',
                            tag=name, id_params=cls.id_params,
                            input_schema=schema(partial=True), output_schema=schema(),
                            extra_args=getattr(cls.update, '__extra_args__', None),
                            auth_required=getattr(cls.update, '__auth_required__', None),
                            description=cls.update.__doc__)
            self.app.add_url_rule(path, view_func=view, methods=['PATCH'])
        if issubclass(cls, DeleteResource):
            self.resource_methods[name].add('DELETE')
            self.add_path(path, view, method='DELETE',
                            tag=name, id_params=cls.id_params,
                            extra_args=getattr(cls.delete, '__extra_args__', None),
                            auth_required=getattr(cls.delete, '__auth_required__', None),
                            status_code=204, description=cls.delete.__doc__)
           
        return cls

    def add_path(self, path, view, method, tag, id_params=None,
                 input_schema=None, output_schema=None, extra_args=None, auth_required=None,
                 status_code=200, description=''):
        swagger_path = self.RE_URL.sub(r'{\2}', path)
        self.app.add_url_rule(path, view_func=view, methods=[method])

        parameters = [
            {'name': id_param.name, 'schema': {'type': id_param.type}, 'in': 'path'}
            for id_param in id_params
        ]
        if extra_args:
            parameters.extend(self.openapi.fields2parameters(extra_args, default_in='query'))

        request_body = {}
        if input_schema:
            request_body['requestBody'] = {
                'description': '',
                'content': {
                    'application/json': {
                        'schema': self.openapi.schema2jsonschema(input_schema)
                    }
                }
            }

        if auth_required is None:
            auth_required = self.default_security_scheme

        self.spec.path(swagger_path, operations={
            method.lower(): {
                'description': description or '',
                'parameters': parameters,
                'responses': {
                    str(status_code): {} if not output_schema else {
                        'description': '',
                        'content': {
                            'application/json': {
                                'schema': output_schema
                            }
                        }
                    }
                },
                'tags': [tag],
                'security': [{auth_required: []}] if auth_required else [],
                **request_body
            }
        })

    def add_blueprint(self, blueprint):
        blueprint.bind(self)
        for cls, args in blueprint.resources:
            self.add_resource(cls, *args)

    def url_for(self, resource_name, _method=None, _external=True, **kwargs):
        if _method is None:
            methods = self.resource_methods[resource_name]
            for desired_method in ('GET', 'PUT', 'DELETE', 'POST'):
                if desired_method in methods:
                    _method = desired_method
                    break
        return url_for('.' + resource_name, _method=_method, _external=_external, **kwargs)


class RestApiBlueprint:

    def __init__(self):
        self.resources = []
        self._rest_api = None  # needs to be binded

    def bind(self, rest_api):
        if self._rest_api is not None:
            raise RuntimeError("blueprints can be bound to one rest api only")
        self._rest_api = rest_api

    def resource(self, path, name, schema):

        def decorator(cls):
            return self.add_resource(cls, path, name, schema)
        
        return decorator

    def add_resource(self, cls, path, name, schema):
        self.resources.append((cls, (path, name, schema)))
        return cls
    
    def add_blueprint(self, blueprint):
        blueprint.bind(self)
        self.resources.extend(blueprint.resources)

    def url_for(self, resource_name, _method=None, _external=True, **kwargs):
        return self._rest_api.url_for(resource_name, _method=_method, _external=_external, **kwargs)


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
