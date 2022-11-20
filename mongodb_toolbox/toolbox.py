import logging
import time
from collections.abc import Callable, Iterable
from copy import deepcopy
from pprint import pformat, pprint  # pylint: disable=unused-import
from typing import Any, Optional, Union

from bson.raw_bson import RawBSONDocument
from pymongo import DeleteOne, InsertOne, UpdateOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError
from pymongo.results import BulkWriteResult

__all__ = [
    "bulk_write",
    "iterate_collection",
    "bulk_insert_dup",
    "bulk_insert_dup_retok",
    "MongodbToolboxError",
    "BulkWriter",
]

StatsCallback = Callable[..., None]
LOG = logging.getLogger(__name__)
DatabaseOperation = Union[UpdateOne, InsertOne, DeleteOne]


class MongodbToolboxError(Exception):
    pass


def dummy_stats_func(_key: str, **_kwargs: Any) -> None:
    pass


def bulk_write(
    db: Database[RawBSONDocument],
    colname: str,
    ops: list[DatabaseOperation],
    stats_callback: StatsCallback = dummy_stats_func,
) -> BulkWriteResult:
    """
    Apply multiple data operations to the collection using mongodb bulk interface.

    :param db: database object
    :param colname: name of collection to write items into
    :param ops: list of mongodb operations
    :param stats_callback: callback to track statistics
    """
    stats_callback("bulk-write-%s-ops" % colname, len(ops))
    bulk_res = db[colname].bulk_write(ops, ordered=False)
    for stats_key, result_key in [
        ("inserted", "nInserted"),
        ("upserted", "nUpserted"),
        ("modified", "nModified"),
    ]:
        stats_callback(
            "{}-{}".format(colname, stats_key),
            bulk_res.bulk_api_result[result_key],
        )
    return bulk_res


class BulkWriter:
    """
    Class to collect mongodb operations and execute them with bulk interface
    when number of pending operations reaches threshold.
    """

    def __init__(
        self,
        db: Database[RawBSONDocument],
        colname: str,
        bulk_size: int = 100,
        stats_callback: StatsCallback = dummy_stats_func,
    ) -> None:
        """
        :param db: database object
        :param colname: name of collection to apply operations to
        :param bulk_size: number of operations to store before run them with bulk interface
        :param stats_callback: callback to track statistics
        """
        self.db = db
        self.colname = colname
        self.stats_callback = stats_callback
        self.bulk_size = bulk_size
        self.ops: list[DatabaseOperation] = []

    def _write_ops(self) -> BulkWriteResult:
        res = bulk_write(
            self.db, self.colname, self.ops, stats_callback=self.stats_callback
        )
        self.ops = []
        return res  # noqa: R504

    def update_one(self, *args: Any, **kwargs: Any) -> Optional[BulkWriteResult]:
        """Add new UpdateOne operation to list of pending operations

        :param \*args: goes directly to UpdateOne constructor
        :param \**kwargs: goes directly to UpdateOne constructor

        If number of operations reaches threshold then execute all operations
        with mongodb bulk interface.
        """
        self.ops.append(UpdateOne(*args, **kwargs))
        if len(self.ops) >= self.bulk_size:
            return self._write_ops()
        return None

    def insert_one(self, *args: Any, **kwargs: Any) -> Optional[BulkWriteResult]:
        """Add new InsertOne operation to list of pending operations

        :param \*args: goes directly to UpdateOne constructor
        :param \**kwargs: goes directly to UpdateOne constructor

        If number of operations reaches threshold then execute all operations
        with mongodb bulk interface.
        """
        self.ops.append(InsertOne(*args, **kwargs))
        if len(self.ops) >= self.bulk_size:
            return self._write_ops()
        return None

    def flush(self) -> Optional[BulkWriteResult]:
        """Run all pending operations"""
        if self.ops:
            return self._write_ops()
        return None


def iterate_collection(  # noqa: CCR001 pylint: disable=too-many-arguments
    db: Database[RawBSONDocument],
    colname: str,
    query: dict[str, Any],
    sort_field: str,
    chunk_len: int = 1000,
    fields: Optional[dict[str, int]] = None,
    infinite: bool = False,
    limit: Optional[int] = None,
    recent_id: Optional[int] = None,
    no_items_sleep_time: int = 5,
) -> Iterable[Any]:
    """
    Iterate items in a collection.

    The function fetches chunk of items at once, iterates over it, then gets next chunk.
    """
    num_items = 0
    query = deepcopy(query)  # avoid possible side effects
    if sort_field in query:
        # During the iteration the function "iterate_collection"
        # uses values of "sort_field" as offset for new chunk of items
        raise MongodbToolboxError(
            'Search query can not contain field from "sort_field" argument'
        )
    while True:
        if recent_id:
            query[sort_field] = {"$gt": recent_id}
        items = list(
            db[colname].find(query, fields, sort=[(sort_field, 1)], limit=chunk_len)
        )
        for item in items:
            yield item
            recent_id = item[sort_field]
            num_items += 1
            if limit and num_items >= limit:
                return
        if not items:
            if not infinite:
                return
            LOG.debug("No items to process. Sleeping %d seconds", no_items_sleep_time)
            time.sleep(no_items_sleep_time)


def only_dup_key_errors(err: BulkWriteError) -> bool:
    return (
        all(x["code"] == 11000 for x in err.details["writeErrors"])
        and not err.details["writeConcernErrors"]
    )


def bulk_insert_dup_retok(  # noqa: CCR001
    db: Database[RawBSONDocument],
    colname: str,
    ops: list[InsertOne[Any]],
    dup_key: Union[str, list[str]],
    stats_callback: StatsCallback = dummy_stats_func,
) -> list[Any]:
    stats_callback("bulk-insert-dup-retok-%s-ops" % colname, len(ops))
    if isinstance(dup_key, str):
        dup_key = [dup_key]
    slots = set()
    uniq_ops: list[InsertOne[Any]] = []
    for op in ops:
        if not isinstance(op, InsertOne):
            raise MongodbToolboxError(
                "Function bulk_insert_dup_retok accepts only"
                " InsertOne operations. Got: {}".format(op.__class__.__name__)
            )
        for key_item in dup_key:
            if key_item not in op._doc:  # pylint: disable=protected-access
                raise MongodbToolboxError(
                    "Operation for bulk_dup_insert"
                    ' does not have key "%s": %s'
                    % (
                        key_item,
                        str(op._doc)[:1000],  # pylint: disable=protected-access
                    )
                )
        slot = tuple(op._doc[x] for x in dup_key)  # pylint: disable=protected-access
        if slot not in slots:
            slots.add(slot)
            uniq_ops.append(op)
    try:
        db[colname].bulk_write(uniq_ops, ordered=False)
    except BulkWriteError as ex:
        if not only_dup_key_errors(ex):
            raise
        error_slots = {
            tuple(err["op"][x] for x in dup_key) for err in ex.details["writeErrors"]
        }
        ret_slots = list(slots - error_slots)
        stats_callback("%s-inserted" % colname, len(ret_slots))
        return ret_slots
    else:
        stats_callback("%s-inserted" % colname, len(slots))
        return list(slots)


def bulk_insert_dup(
    db: Database[RawBSONDocument],
    colname: str,
    ops: list[InsertOne[Any]],
    stats_callback: StatsCallback = dummy_stats_func,
) -> None:
    """Write multiple insert operations ignoring all duplicate key errors."""
    stats_callback("bulk-insert-dup-%s-ops" % colname, len(ops))
    for op in ops:
        if not isinstance(op, InsertOne):
            raise MongodbToolboxError(
                "Function simple_bulk_insert accepts only"
                " InsertOne operations. Got: %s" % op.__class__.__name__
            )
    try:
        db[colname].bulk_write(ops, ordered=False)
    except BulkWriteError as ex:
        if not only_dup_key_errors(ex):
            raise
        stats_callback(
            "%s-inserted" % colname,
            len(ops) - len(ex.details["writeErrors"]),
        )
    else:
        stats_callback("%s-inserted" % colname, len(ops))
