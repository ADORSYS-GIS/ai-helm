# MongoDB Restoration Guide

This document describes the process for restoring the MongoDB database in the production Kubernetes cluster, using the artifacts in the `recoveries/librechat` directory.

## 1. Local Verification using Docker Compose

Before performing the restoration in production, the process was verified locally using Docker Compose to ensure the backup file's integrity and the correctness of the `mongorestore` command.

### Environment Setup
- **Image**: `mongo:8.0.11`
- **Backup File**: `all-databases_20260415_020035.gz` (gzip archive)

### Local Restoration Steps
1. **Start the local MongoDB instance**:
   ```bash
   docker compose up -d mongodb
   ```
2. **Execute the restoration using the `restore` profile**:
   ```bash
   docker compose --profile restore up mongorestore
   ```

### Verification
- The `mongorestore` container waits for the `mongodb` service to be healthy before starting.
- It mounts the local directory as `/backup` and runs the following command:
  ```bash
  mongorestore --host mongodb --port 27017 \
    --username ${MONGO_INITDB_ROOT_USERNAME} \
    --password ${MONGO_INITDB_ROOT_PASSWORD} \
    --authenticationDatabase admin \
    --drop --gzip --archive=/backup/all-databases_20260415_020035.gz
  ```

---

## 2. Production Deployment

The production restoration is carried out using a standalone Kubernetes Pod deployed in the `converse-chat` namespace.

### Restoration Process
The restoration is automated through a multi-stage `Pod` execution defined in `recoveries/librechat/mongorestore-pod.yaml`:

1. **Backup Download (Init Container: `download-backup`)**:
   - Uses `minio/mc` to pull the backup from S3-compatible storage (`s3.ssegning.me`).
   - Credentials are provided via the `librechat-s3-config` secret.
   - The backup `mongodb-backup/all-databases_20260415_020035.gz` is downloaded to a shared volume at `/backup/backup.archive`.

2. **Database Preparation**:
   - Before restoration, we clean the existing environment by dropping all non-system databases (`admin`, `local`, `config`).
   - This is performed via a `mongosh` script within the main container.

3. **Restoration Execution (Main Container: `mongorestore`)**:
   - Uses `mongo:8.2.6`.
   - Connects to the production database: `mongodb://librechat-db-0.librechat-db-headless:27017`.
   - Executes `mongorestore` with `--drop` and `--gzip` flags.

### Deployment via ArgoCD
- **Note**: By default, the `recoveries/` directory is **not** automatically synced by the main ArgoCD applications.
- To perform the restoration in production, the manifest must be **manually applied** using `kubectl`:
  ```bash
  kubectl apply -f recoveries/librechat/mongorestore-pod.yaml
  ```
- Alternatively, a temporary ArgoCD Application can be created to track the `recoveries/librechat` path for a managed restoration process.
- Once applied, monitoring is performed through the ArgoCD UI or `kubectl logs`.

> [!IMPORTANT]
> Because this is a one-time restoration task, it is intentionally excluded from the automated sync to prevent accidental repeated restorations on every git commit.


---

## 3. Verification in Kubernetes

After the restoration job completes, the following steps are used to ensure success:

1. **Pod Exit Code**:
   - Verify that the `librechat-mongorestore` pod terminated with exit code `0`.
2. **Data Integrity**:
   - Connect to the database and check the collection counts against metadata from the backup time.
3. **Connectivity**:
   - Ensure the `librechat` application can successfully connect and query the restored data.
4. **Log Review**:
   - Inspect the logs of the `mongorestore` container to confirm that all namespaces were processed correctly without errors.
