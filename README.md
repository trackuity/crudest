# crudest

CRUD-structured REST APIs in Python, using [Flask](http://flask.pocoo.org/), [marshmallow](http://marshmallow.readthedocs.io/), [webargs](http://webargs.readthedocs.io/) and [apispec](http://apispec.readthedocs.io/).

With **crudest** you can write your REST API like so:

```python
from flask import Flask
from crudest import RestApi, CreateResource, RetrieveResource, UpdateResource, DeleteResource

from models import Cat  # e.g. ndb models
from schemas import CatSchema, CatActionSchema  # marshmallow schemas

app = Flask(__name__)
api = RestApi(app, title='Cat API', version='v1')

@api.resource('/cats/<int:cat_id>', name='Cat', schema=CatSchema)
class CatResource(CreateResource, RetrieveResource, UpdateResource, DeleteResource):

    def create(self, **kwargs):
        cat = Cat(**kwargs)
        cat.put()
        return cat

    def list(self):
        return Cat.query()

    def retrieve(self, cat_id):
        # ...

    def update(self, cat_id):
        # ...

    def delete(self, cat_id):
        # ...

@api.resource('/cats/<int:cat_id>/actions/<int:action_id>', name='CatAction', schema=CatActionSchema)
class CatActionResource(CreateResource):

    def create(self, cat_id):
        # ...
```

All of the necessary REST endpoints get created under the hood and implementing the required methods is enforced using abstract base classes. Also, both the input and output parsing are handled automagically using the provided marshmallow schemas. You even get [swagger](https://swagger.io/) documentation for free, served on `/docs` by default using [flask-swagger-ui](https://github.com/sveint/flask-swagger-ui).
