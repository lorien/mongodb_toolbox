# MongoDB Toolbox

Tools to automate mongodb read/write operations.

Bulk Write Helpers:

* bulk\_write() -- function to execute a list of data operations
* BulkWriter -- class for accumulating and executing data operations
* bulk\_insert\_dup\_retok -- function to write list of insert operations and return list of keys which has been inserted
* bulk\_insert_\dup -- function to write list of insert operations ignoring any duplicate key error

Misc functions:

* iterate\_collection() -- function to iterate items in collecting by loading them by chunks
