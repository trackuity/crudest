from setuptools import setup

setup(
    name = 'crudest',
    version = '0.7',
    description = 'CRUD-structured REST APIs in Python, using Flask, marshmallow, webargs and apispec',
    license = 'Apache Software License (ASF)',
    url = 'https://github.com/trackuity/crudest',
    py_modules = ['crudest'],
    install_requires = ['Flask', 'apispec>3.0', 'webargs==6', 'marshmallow>3.0',
                        'flask-swagger-ui>3.0', 'Flask-JWT-Extended']
)
