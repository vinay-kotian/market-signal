"""Pre-existing ACTIVE levels for regression tests of rules after initial arming.

These scenarios intentionally start after initial arming (as migrated levels do).
Initial-arm transitions are tested end-to-end in test_initial_arming.py.
"""
from app.database import connect


def create_active_level(client, json):
    response = client.post('/levels', json=json)
    if response.status_code == 201:
        with connect(client.app.state.database_path) as connection:
            connection.execute("UPDATE levels SET status = 'ACTIVE' WHERE id = ? AND status = 'PENDING_ARM'",
                               (response.json()['id'],))
        result = client.get('/levels/' + str(response.json()['id']))
        result.status_code = 201
        return result
    return response


def create_active_record(repository, data):
    level = repository.create(data)
    with connect(repository.database_path) as connection:
        connection.execute("UPDATE levels SET status = 'ACTIVE' WHERE id = ? AND status = 'PENDING_ARM'", (level.id,))
    return repository.get(level.id)
