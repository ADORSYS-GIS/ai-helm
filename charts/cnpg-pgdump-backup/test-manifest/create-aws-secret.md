```bash
kubectl create secret generic open-web-ui-s3 \
  -n pgdump-test \
  --from-literal=S3_BUCKET_NAME=kivoyo-backup-postgresdb-test \
  --from-literal=S3_REGION_NAME=eu-north-1 \
  --from-literal=S3_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
  --from-literal=S3_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
  --from-literal=AWS_SESSION_TOKEN="$AWS_SESSION_TOKEN" \
  --dry-run=client -o yaml | kubectl apply -f -   
```