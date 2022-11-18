import logging
import time
from collections.abc import Iterable
from copy import deepcopy
from pprint import pformat, pprint  # pylint: disable=unused-import
from typing import Any, Optional, Union, cast

from bson.raw_bson import RawBSONDocument
from procstat import Stat
from pymongo import DeleteOne, InsertOne, UpdateOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError
from pymongo.results import BulkWriteResult

DatabaseOperation = Union[UpdateOne, InsertOne, DeleteOne]


__all__ = ["bulk_write", "iterate_collection", "bulk_dup_insert", "bulk_simple_insert"]


def bulk_write(
    db: Database[RawBSONDocument],
    item_type: str,
    ops: list[DatabaseOperation],
    stat: Optional[Stat] = None,
    retries: int = 3,
    log_first_failop: bool = True,
) -> BulkWriteResult:
    """
    Apply `ops` Update operations to `item_type` collection with `bulk_write` method.

    Gives up if `retries` retries failed.

    Args:
        db - pymongo collection object
        item_type - name of collection
        ops - list of operations like UpdateOne
        stat - instance of `ioweb.stat:Stat`
        retries - number of retries
    """
    if stat:
        stat.inc("bulk-write-%s" % item_type)
    bulk_res = None
    for retry in range(retries):
        try:
            bulk_res = db[item_type].bulk_write(ops, ordered=False)
        except BulkWriteError as ex:
            # TODO: repeat only failed operations!!!
            # TODO: repeat only in case of DUP (11000) errors
            if retry == (retries - 1):
                if log_first_failop:
                    logging.error(
                        "First failed operation:\n%s",
                        pformat(ex.details["writeErrors"][0]),
                    )
                raise
            if stat:
                stat.inc("bulk-write-%s-retry" % item_type)
        else:
            if stat:
                stat.inc(
                    "bulk-write-%s-upsert" % item_type,
                    bulk_res.bulk_api_result["nUpserted"],
                )
                stat.inc(
                    "bulk-write-%s-change" % item_type,
                    bulk_res.bulk_api_result["nModified"],
                )
    return cast(BulkWriteResult, bulk_res)


class BulkWriter:
    def __init__(
        self,
        db: Database[RawBSONDocument],
        item_type: str,
        bulk_size: int = 100,
        stat: Optional[Stat] = None,
        retries: int = 3,
    ) -> None:
        self.db = db
        self.item_type = item_type
        self.stat = stat
        self.retries = retries
        self.bulk_size = bulk_size
        self.ops: list[DatabaseOperation] = []

    def _write_ops(self) -> BulkWriteResult:
        res = bulk_write(self.db, self.item_type, self.ops, self.stat)
        self.ops = []
        return res  # noqa: R504

    def update_one(self, *args: Any, **kwargs: Any) -> Optional[BulkWriteResult]:
        self.ops.append(UpdateOne(*args, **kwargs))
        if len(self.ops) >= self.bulk_size:
            return self._write_ops()
        return None

    def insert_one(self, *args: Any, **kwargs: Any) -> Optional[BulkWriteResult]:
        self.ops.append(InsertOne(*args, **kwargs))
        if len(self.ops) >= self.bulk_size:
            return self._write_ops()
        return None

    def flush(self) -> Optional[BulkWriteResult]:
        if self.ops:
            return self._write_ops()
        return None


def iterate_collection(
    db: Database[RawBSONDocument],
    item_type: str,
    query: dict[str, Any],
    sort_field: str,
    iter_chunk: int = 1000,
    fields: Optional[dict[str, int]] = None,
    infinite: bool = False,
    limit: Optional[int] = None,
    recent_id: Optional[int] = None,
) -> Iterable[Any]:
    """
    Iterate items in a collection, extracting them by chunks.

    Intenally, it fetches chunk of `iter_chunk` items at once and
    iterates over it. Then fetch next chunk.
    """
    count = 0
    query = deepcopy(query)  # avoid side effects
    if sort_field in query:
        raise Exception(
            "Function `iterate_collection` received query"
            " that contains a key same as `sort_field`."
        )
    while True:
        if recent_id:
            query[sort_field] = {"$gt": recent_id}
        items = list(
            db[item_type].find(query, fields, sort=[(sort_field, 1)], limit=iter_chunk)
        )
        if not items:
            if infinite:
                sleep_time = 5
                logging.debug("No items to process. Sleeping %d seconds", sleep_time)
                time.sleep(sleep_time)
                recent_id = None
            else:
                return
        else:
            for item in items:
                yield item
                recent_id = item[sort_field]
                count += 1
                if limit and count >= limit:
                    return


def bulk_dup_insert(
    db: Database[RawBSONDocument],
    item_type: str,
    ops: list[DatabaseOperation],
    dup_key: Union[str, list[str]],
    stat: Optional[Stat] = None,
) -> list[Any]:
    # normalize dup_key to list
    assert isinstance(dup_key, (str, tuple, list))
    if isinstance(dup_key, str):
        dup_key = [dup_key]
    if stat:
        stat.inc("bulk-dup-insert-%s" % item_type, len(ops))
    slots = set()
    uniq_ops = []
    for op in ops:
        if not isinstance(op, InsertOne):
            raise Exception(
                "Function bulk_dup_insert accepts only"
                " InsertOne operations. Got: %s" % op.__class__.__name__
            )
        for key_item in dup_key:
            if key_item not in op._doc:  # pylint: disable=protected-access
                raise Exception(
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
        db[item_type].bulk_write(uniq_ops, ordered=False)
    except BulkWriteError as ex:
        if (
            all(x["code"] == 11000 for x in ex.details["writeErrors"])
            and not ex.details["writeConcernErrors"]  # noqa: W503
        ):
            error_slots = {
                tuple(err["op"][x] for x in dup_key)
                for err in ex.details["writeErrors"]
            }
            res_slots = list(slots - error_slots)
            if stat:
                stat.inc("bulk-dup-insert-%s-inserted" % item_type, len(res_slots))
            return res_slots
        raise
    else:
        if stat:
            stat.inc("bulk-dup-insert-%s-inserted" % item_type, len(slots))
        return list(slots)


def bulk_simple_insert(
    db: Database[RawBSONDocument],
    item_type: str,
    ops: list[DatabaseOperation],
    stat: Optional[Stat] = None,
) -> None:
    if stat:
        stat.inc("bulk-dup-insert-%s" % item_type, len(ops))
    for op in ops:
        if not isinstance(op, InsertOne):
            raise Exception(
                "Function simple_bulk_insert accepts only"
                " InsertOne operations. Got: %s" % op.__class__.__name__
            )
    try:
        db[item_type].bulk_write(ops, ordered=False)
    except BulkWriteError as ex:
        if (
            all(x["code"] == 11000 for x in ex.details["writeErrors"])
            and not ex.details["writeConcernErrors"]
        ):
            if stat:
                stat.inc(
                    "bulk-dup-insert-%s-inserted" % item_type,
                    len(ops) - len(ex.details["writeErrors"]),
                )
        else:
            raise
    else:
        if stat:
            stat.inc("bulk-dup-insert-%s-inserted" % item_type, len(ops))
