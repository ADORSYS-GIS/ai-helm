To recover from `mongodump` files, you use **`mongorestore`**. MongoDB’s current docs confirm that `mongorestore` restores dump directories, compressed dumps with `--gzip`, and archive files with `--archive`. ([MongoDB][1])

The right command depends on **what your backup looks like**:

**1. Restore a normal dump directory**

```bash
mongorestore --uri="mongodb://localhost:27017" /path/to/dump
```

If your dump folder contains multiple databases, this restores them all. MongoDB’s examples show restoring from the `dump/` directory directly. ([MongoDB][2])

**2. Restore one database only**

```bash
mongorestore --uri="mongodb://localhost:27017" --nsInclude="mydb.*" /path/to/dump
```

`--nsInclude="mydb.*"` limits the restore to that database. ([MongoDB][3])

**3. Restore a gzip-compressed dump directory**

```bash
mongorestore --uri="mongodb://localhost:27017" --gzip /path/to/dump
```

Use `--gzip` when the dump files were created with `mongodump --gzip`. ([MongoDB][1])

**4. Restore an archive file**

```bash
mongorestore --uri="mongodb://localhost:27017" --archive=/path/to/backup.archive
```

For a compressed archive:

```bash
mongorestore --uri="mongodb://localhost:27017" --gzip --archive=/path/to/backup.gz
```

MongoDB documents both archive and gzip+archive restores. ([MongoDB][1])

**5. Drop existing data before restore**

```bash
mongorestore --uri="mongodb://localhost:27017" --drop /path/to/dump
```

Use `--drop` if you want to replace existing collections instead of merging into what is already there. This is the usual choice when rebuilding a database from backup. ([MongoDB][1])

**6. Restore into a different database name**

```bash
mongorestore --uri="mongodb://localhost:27017" \
  --nsFrom="olddb.*" \
  --nsTo="newdb.*" \
  /path/to/dump
```

MongoDB supports namespace remapping with `--nsFrom` and `--nsTo`. ([MongoDB][3])

A typical real example looks like this:

```bash
mongorestore --uri="mongodb://user:pass@host:27017/admin" --drop /backups/dump
```

A few common gotchas:

* Restore from the **top-level dump folder**, not from too far inside it. A normal dump usually looks like `dump/mydb/collection.bson`. ([MongoDB][3])
* If authentication is enabled, include the correct URI, username/password, and auth database. MongoDB’s examples note adding connection/auth options as needed. ([MongoDB][3])
* Use recent **MongoDB Database Tools** versions for `mongodump` and `mongorestore`. ([MongoDB][4])

If you show me the output of `ls -R` inside your backup folder, or the exact filename pattern you have, I can give you the exact `mongorestore` command for your case.

[1]: https://www.mongodb.com/docs/database-tools/mongorestore/?utm_source=chatgpt.com "mongorestore - Database Tools - MongoDB Docs"
[2]: https://www.mongodb.com/docs/manual/tutorial/backup-and-restore-tools/?utm_source=chatgpt.com "Back Up and Restore a Self-Managed Deployment with ..."
[3]: https://www.mongodb.com/docs/database-tools/mongorestore/mongorestore-examples/?utm_source=chatgpt.com "mongorestore Examples - Database Tools"
[4]: https://www.mongodb.com/docs/database-tools/?utm_source=chatgpt.com "The MongoDB Database Tools Documentation"
