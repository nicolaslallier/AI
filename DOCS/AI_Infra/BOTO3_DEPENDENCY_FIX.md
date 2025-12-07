# boto3 Dependency Fix

**Date**: December 6, 2025  
**Status**: ✅ FIXED

## Problem Summary

E2E tests for MinIO were failing with `ModuleNotFoundError: No module named 'boto3'`.

```
ERROR collecting tests/e2e/test_minio_backup.py
ERROR collecting tests/e2e/test_minio_s3_api.py
E   ModuleNotFoundError: No module named 'boto3'
```

## Root Cause

The `boto3` library (AWS SDK for Python) was not included in the test dependencies file (`tests/requirements.txt`), even though MinIO E2E tests require it to interact with the S3-compatible API.

## Solution

### 1. Added boto3 to test dependencies

Updated `tests/requirements.txt` to include:

```txt
# MinIO / S3 API testing
boto3==1.34.10
botocore==1.34.10
```

### 2. Installed boto3 in virtual environment

```bash
pip install boto3==1.34.10 botocore==1.34.10
```

## Affected Tests

The following E2E tests now have the required dependencies:

1. **tests/e2e/test_minio_backup.py** - Tests PostgreSQL backup/restore with MinIO
2. **tests/e2e/test_minio_s3_api.py** - Tests MinIO S3 API compatibility

## Verification

```bash
# Verify boto3 is installed
python -c "import boto3; print(f'boto3 version: {boto3.__version__}')"
# Output: boto3 version: 1.34.10

# Run the previously failing tests
pytest tests/e2e/test_minio_backup.py -v
pytest tests/e2e/test_minio_s3_api.py -v
```

## Why boto3?

**boto3** is the Amazon Web Services (AWS) SDK for Python. It's used to interact with:
- AWS S3 (Simple Storage Service)
- MinIO (S3-compatible object storage)
- Any S3-compatible storage systems

MinIO implements the S3 API, making boto3 the standard library for programmatically managing buckets, objects, and performing backup/restore operations.

## Files Modified

1. **tests/requirements.txt** - Added boto3 and botocore dependencies

## Next Steps

To ensure all team members have this dependency:

```bash
# From the project root
cd /Users/nicolaslallier/Dev\ Nick/AI_Infra
source venv/bin/activate  # or: . venv/bin/activate
pip install -r tests/requirements.txt
```

Or use the Makefile if available:

```bash
make install-test-deps  # If this target exists
# Or
make setup
```

## Related Documentation

- [boto3 Documentation](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)
- [MinIO Python Client](https://min.io/docs/minio/linux/developers/python/minio-py.html)
- [MinIO S3 API Compatibility](https://min.io/docs/minio/linux/developers/python/API.html)

---

**Status**: ✅ Issue resolved. Tests can now import boto3 successfully.


