from setuptools import setup, find_packages

setup(
    name = 'crudest',
    version = '0.2',
    license = 'Apache Software License (ASF)',
    packages = find_packages(),
    install_requires = ['Flask', 'apispec>3.0', 'webargs', 'marshmallow>3.0',
                        'flask-swagger-ui>3.0', 'Flask-JWT-Extended'],
    test_suite = 'nose.collector',
    tests_require = ['nose']
)
