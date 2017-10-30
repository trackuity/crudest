from setuptools import setup, find_packages

setup(
    name = 'crudest',
    version = '0.1',
    license = 'Apache Software License (ASF)',
    packages = find_packages(),
    install_requires = ['Flask', 'apispec', 'webargs', 'marshmallow', 'flask-swagger-ui'],
    test_suite = 'nose.collector',
    tests_require = ['nose']
)
