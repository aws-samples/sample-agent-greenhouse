# IAM & Permissions Debugging Guide

## Table of Contents
- [Access Denied Errors](#access-denied-errors)
- [Role Assumption Failures](#role-assumption-failures)
- [Missing Policies](#missing-policies)
- [Cross-Account Access](#cross-account-access)
- [Credential Chain Issues](#credential-chain-issues)
- [Service-Linked Roles](#service-linked-roles)

---

## Access Denied Errors

### Symptom: AccessDeniedException on API call

**Diagnosis:**
```bash
# Check current identity
aws sts get-caller-identity

# Check what permissions are needed
# Look at the error message — it usually includes the action and resource

# Use IAM Policy Simulator
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::<account>:role/<role> \
  --action-names bedrock:InvokeModel \
  --resource-arns "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-*"
```

**Common causes:**
1. IAM role missing required permissions
2. Resource-based policy denying access
3. SCP (Service Control Policy) blocking the action
4. Condition key mismatch (region, source IP, etc.)

**Fixes:**
- Add the specific permission to the role's policy
- Check for explicit Deny statements (they override Allow)
- Verify the resource ARN format matches exactly
- Check if there's an SCP at the organization level

### Symptom: AccessDenied on S3 from agent

```bash
# Check bucket policy
aws s3api get-bucket-policy --bucket <bucket>

# Check if agent's role has s3:GetObject
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::<account>:role/<agent-role> \
  --action-names s3:GetObject \
  --resource-arns "arn:aws:s3:::<bucket>/*"
```

---

## Role Assumption Failures

### Symptom: "is not authorized to perform: sts:AssumeRole"

**Diagnosis:**
```bash
# Check the trust policy of the target role
aws iam get-role --role-name <target-role> \
  --query 'Role.AssumeRolePolicyDocument'

# Verify the calling identity
aws sts get-caller-identity
```

**Common causes:**
1. Trust policy doesn't include the calling principal
2. External ID required but not provided
3. MFA required but not used
4. Session duration exceeds maximum

**Fixes:**
- Update trust policy to include AgentCore service principal
- Add `bedrock.amazonaws.com` to trusted entities
- Check `sts:ExternalId` condition if cross-account

### Trust policy template for AgentCore:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "aws:SourceAccount": "<your-account-id>"
        }
      }
    }
  ]
}
```

---

## Missing Policies

### Symptom: Agent can't invoke Bedrock models

**Required permissions:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:*::foundation-model/*"
    }
  ]
}
```

### Symptom: Agent can't write CloudWatch logs

**Required permissions:**
```json
{
  "Effect": "Allow",
  "Action": [
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents"
  ],
  "Resource": "arn:aws:logs:*:*:log-group:/agentcore/*"
}
```

---

## Cross-Account Access

### Symptom: Can't access resources in another account

**Diagnosis:**
```bash
# Check if the resource account allows cross-account access
# For S3:
aws s3api get-bucket-policy --bucket <cross-account-bucket>
# For KMS:
aws kms get-key-policy --key-id <key-id> --policy-name default
```

**Setup pattern:**
1. Target account: Create role with trust policy for your account
2. Your account: Grant sts:AssumeRole on the target role
3. Agent code: Use STS to assume the cross-account role

---

## Credential Chain Issues

### Symptom: "Unable to locate credentials"

**Diagnosis order (SDK credential chain):**
1. Environment variables (`AWS_ACCESS_KEY_ID`, etc.)
2. Shared credential file (`~/.aws/credentials`)
3. Container credentials (ECS/AgentCore task role)
4. Instance metadata (EC2 instance profile)

```bash
# Check environment
env | grep AWS_

# Check if container role is available
curl -s http://169.254.170.2$AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
```

**Fix:** In AgentCore, credentials come from the task role. Don't set
`AWS_ACCESS_KEY_ID` manually — let the SDK use the container credential provider.

---

## Service-Linked Roles

### Symptom: "Service role does not exist"

**Diagnosis:**
```bash
# Check if the service-linked role exists
aws iam get-role \
  --role-name AWSServiceRoleForBedrockAgentCore 2>/dev/null || \
  echo "Role does not exist"
```

**Fix:**
```bash
# Create the service-linked role
aws iam create-service-linked-role \
  --aws-service-name agentcore.bedrock.amazonaws.com
```

Note: Service-linked roles are created automatically on first use in most cases.
If creation fails, check if your account has permission to create service-linked roles.
