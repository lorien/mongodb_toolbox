from collections import defaultdict

import pytest
from pymongo import InsertOne, MongoClient
from pymongo.errors import BulkWriteError

from mongodb_toolbox import bulk_write

CONFIG = {
    "TEST_DBNAME": "test",
    "TEST_COLNAME": "foo",
}


def connect_db():
    return MongoClient()[CONFIG["TEST_DBNAME"]]


class DummyStat:
    def __init__(self):
        self.counters = defaultdict(int)

    def inc(self, key, count=1):
        self.counters[key] += count


@pytest.fixture(name="stat", scope="function")
def fixture_stat():
    return DummyStat()


@pytest.fixture(name="database", scope="function")
def fixture_database():
    return connect_db()


@pytest.fixture(name="collection", scope="function")
def fixture_collection(database):
    col = database[CONFIG["TEST_COLNAME"]]
    col.drop()
    return col


def test_bulk_write(stat, database, collection):
    ops = []
    for idx in range(10):
        ops.append(InsertOne({"idx": idx}))
    bulk_write(database, collection.name, ops, stat.inc)

    assert stat.counters["bulk-write-foo-inserted"] == 10
    assert collection.count_documents({}) == 10


def test_bulk_write_dup_error(stat, database, collection):
    ops = []
    for _ in range(2):
        ops.append(InsertOne({"_id": 0}))
    with pytest.raises(BulkWriteError):
        bulk_write(database, collection.name, ops, stat.inc)
