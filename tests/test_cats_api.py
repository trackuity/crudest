from decimal import Decimal
from requests_flask_adapter import Session

import pytest

from crudest import create_access_token, create_refresh_token

from .cat_api import app, db


@pytest.fixture
def client():
    # fancier alternative for app.test_client() that uses requests
    app.config['SERVER_NAME'] = 'feline.io'
    Session.register('http://feline.io', app)
    return Session()


@pytest.fixture
def access_token():
    with app.app_context():
        yield create_access_token(identity=1, fresh=True)


@pytest.fixture
def refresh_token():
    with app.app_context():
        yield create_refresh_token(identity=1)


@pytest.fixture
def database():
    db.clear()
    db['User'][1] = {'id': 1, 'name': 'Jon Arbuckle'}
    db['Cat'][1] = {'id': 1, 'name': 'Garfield', 'weight': Decimal('24.67')}
    db['Cat'][2] = {'id': 2, 'name': 'Leftfield', 'weight': Decimal('23.28')}
    db['Cat'][3] = {'id': 3, 'name': 'Rightfield', 'weight': Decimal('22.73')}
    db['CatWhisker'][1] = {'id': 1, 'cat_id': 1, 'length': Decimal('10.57')}
    db['CatWhisker'][2] = {'id': 2, 'cat_id': 1, 'length': Decimal('11.03')}
    db['CatWhisker'][3] = {'id': 3, 'cat_id': 1, 'length': Decimal('9.95')}
    db['CatWhisker'][4] = {'id': 4, 'cat_id': 1, 'length': Decimal('10.34')}
    db['CatSync']['URQpbCZ28urcWnEEeCOh3JAbol0XlAax'] = {'id': 'URQpbCZ28urcWnEEeCOh3JAbol0XlAax', 'done': True}
    return db


def test_create_cat(client, access_token, database):
    name = 'Simba'
    weight = Decimal('12.34')

    rv = client.post('http://feline.io/cats', headers={
        'Authorization': 'Bearer ' + access_token
    }, data={
        'name': name,
        'weight': weight
    })

    assert rv.status_code == 201
    stored = database['Cat'][rv.json()['id']]
    assert stored['name'] == name
    assert stored['weight'] == weight


def test_create_cat_whisker(client, access_token, database):
    cat_id = 1
    length = Decimal('12.34')

    rv = client.post(f'http://feline.io/cats/{cat_id}/whiskers', headers={
        'Authorization': 'Bearer ' + access_token
    }, data={
        'length': length
    })

    assert rv.status_code == 201
    stored = database['CatWhisker'][rv.json()['id']]
    assert stored['cat_id'] == cat_id
    assert stored['length'] == length


def test_create_cat_action(client, access_token, database):
    cat_id = 1
    verb = 'meow'

    rv = client.post(f'http://feline.io/cats/{cat_id}/actions', headers={
        'Authorization': 'Bearer ' + access_token
    }, data={
        'verb': verb
    })

    assert rv.status_code == 201
    assert rv.json()['links']['collection'] == 'http://feline.io/cats/1/actions'


def test_create_cat_sync(client, access_token, database):
    cat_id = 1

    rv = client.post(f'http://feline.io/cats/{cat_id}/syncs', headers={
        'Authorization': 'Bearer ' + access_token
    })

    assert rv.status_code == 201
    assert not rv.json()['done']


def test_list_cats(client, access_token, database):
    rv = client.get('http://feline.io/cats', headers={
        'Authorization': 'Bearer ' + access_token
    })
    results = rv.json()

    assert rv.status_code == 200
    assert isinstance(results, list)
    assert len(results) == 2  # page size is 2

    first_result = results[0]
    stored = database['Cat'][1]
    for key in stored.keys():
        assert str(first_result[key]) == str(stored[key])  # to str because decimals

    assert 'link' in rv.headers
    assert rv.links['self']['url'] == 'http://feline.io/cats'
    assert rv.links['next']['url'] == 'http://feline.io/cats?page=2'

    rv = client.get(f'http://feline.io/cats?page=2', headers={
        'Authorization': 'Bearer ' + access_token
    })
    results = rv.json()

    assert rv.status_code == 200
    assert len(results) == 1  # only 1 left on last page
    assert 'next' not in rv.links


def test_list_cat_whiskers(client, access_token, database):
    rv = client.get('http://feline.io/cats/1/whiskers', headers={
        'Authorization': 'Bearer ' + access_token
    })
    results = rv.json()

    assert rv.status_code == 200
    assert isinstance(results, dict)
    assert 'data' in results
    assert len(results['data']) == 3  # page size is 3

    first_result = results['data'][0]
    stored = database['CatWhisker'][1]
    for key in stored.keys():
        assert str(first_result[key]) == str(stored[key])  # to str because decimals

    assert 'links' in results
    assert results['links']['self'] == 'http://feline.io/cats/1/whiskers'
    assert results['links']['next'] == 'http://feline.io/cats/1/whiskers?page=2'

    rv = client.get(f'http://feline.io/cats/1/whiskers?page=2', headers={
        'Authorization': 'Bearer ' + access_token
    })
    results = rv.json()

    assert rv.status_code == 200
    assert len(results['data']) == 1  # only 1 left on last page
    assert 'next' not in results['links']


def test_retrieve_cat(client, access_token, database):
    rv = client.get('http://feline.io/cats/1', headers={
        'Authorization': 'Bearer ' + access_token
    })
    result = rv.json()

    assert rv.status_code == 200
    stored = database['Cat'][1]
    for key in stored.keys():
        assert str(result[key]) == str(stored[key])  # to str because decimals


def test_retrieve_cat_whisker(client, access_token, database):
    rv = client.get('http://feline.io/cats/1/whiskers/1', headers={
        'Authorization': 'Bearer ' + access_token
    })
    result = rv.json()

    assert rv.status_code == 200
    stored = database['CatWhisker'][1]
    for key in stored.keys():
        assert str(result[key]) == str(stored[key])  # to str because decimals


def test_retrieve_cat_sync(client, access_token, database):
    cat_sync_id = 'URQpbCZ28urcWnEEeCOh3JAbol0XlAax'

    rv = client.get(f'http://feline.io/cats/1/syncs/{cat_sync_id}', headers={
        'Authorization': 'Bearer ' + access_token
    })
    result = rv.json()

    assert rv.status_code == 200
    stored = database['CatSync'][cat_sync_id]
    for key in stored.keys():
        assert result[key] == stored[key]


def test_update_cat(client, access_token, database):
    name = 'Garfield aka The Fat Cat'

    rv = client.put('http://feline.io/cats/1', headers={
        'Authorization': 'Bearer ' + access_token
    }, data={
        'name': name
    })
    result = rv.json()

    assert rv.status_code == 200
    stored = database['Cat'][result['id']]
    assert stored['name'] == name
    assert stored['weight'] == Decimal(result['weight'])


def test_update_cat_whisker(client, access_token, database):
    length = Decimal('9.99')

    rv = client.put('http://feline.io/cats/1/whiskers/1', headers={
        'Authorization': 'Bearer ' + access_token
    }, data={
        'length': length
    })
    result = rv.json()

    assert rv.status_code == 200
    stored = database['CatWhisker'][result['id']]
    assert stored['length'] == Decimal(result['length'])


def test_delete_cat(client, access_token, database):
    rv = client.delete('http://feline.io/cats/1', headers={
        'Authorization': 'Bearer ' + access_token
    })

    assert rv.status_code == 204
    assert 1 not in database['Cat']
    assert 1 not in set(cw['cat_id'] for cw in database['CatWhisker'].values())


def test_delete_cat_whisker(client, access_token, database):
    rv = client.delete('http://feline.io/cats/1/whiskers/1', headers={
        'Authorization': 'Bearer ' + access_token
    })

    assert rv.status_code == 204
    assert 1 not in database['CatWhisker']
