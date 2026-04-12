# Networking Debugging Guide

## Table of Contents
- [VPC Connectivity](#vpc-connectivity)
- [Security Groups](#security-groups)
- [NAT Gateway](#nat-gateway)
- [DNS Resolution](#dns-resolution)
- [Endpoint Configuration](#endpoint-configuration)
- [TLS/Certificate Errors](#tlscertificate-errors)

---

## VPC Connectivity

### Symptom: Agent can't reach external services

**Diagnosis:**
```bash
# Check VPC configuration
aws ec2 describe-vpcs --vpc-ids <vpc-id>

# Check subnet routing
aws ec2 describe-route-tables \
  --filters "Name=association.subnet-id,Values=<subnet-id>"

# Test connectivity from within the container
curl -v --connect-timeout 5 https://api.example.com
```

**Common causes:**
1. Subnet has no internet gateway or NAT gateway
2. Route table missing default route
3. Network ACL blocking traffic
4. Wrong subnet type (public vs private)

**Fixes:**
- Private subnets need NAT gateway for internet access
- Public subnets need internet gateway + public IP
- Check both inbound and outbound NACL rules
- Verify route table has `0.0.0.0/0` route to IGW or NAT

---

## Security Groups

### Symptom: Connection timeout to/from agent

**Diagnosis:**
```bash
# Check security group rules
aws ec2 describe-security-groups --group-ids <sg-id>

# Check outbound rules (often overlooked)
aws ec2 describe-security-groups --group-ids <sg-id> \
  --query 'SecurityGroups[0].IpPermissionsEgress'
```

**Common causes:**
1. Missing outbound rule for HTTPS (port 443)
2. Missing inbound rule for health checks
3. Security group referencing wrong CIDR
4. Stale security group rules after VPC changes

**Fixes:**
- Allow outbound HTTPS (443) to `0.0.0.0/0` or specific endpoints
- Allow inbound on agent port from health check CIDR
- Use VPC endpoint security groups for AWS service access

### Minimum security group rules for AgentCore:
```
Inbound:
  - Port 8080 (or configured port) from VPC CIDR (health checks)

Outbound:
  - Port 443 to 0.0.0.0/0 (AWS APIs, model invocation)
  - Port 443 to VPC endpoint security groups (if using endpoints)
```

---

## NAT Gateway

### Symptom: Private subnet can't reach internet

**Diagnosis:**
```bash
# Check NAT gateway status
aws ec2 describe-nat-gateways \
  --filter "Name=vpc-id,Values=<vpc-id>"

# Verify route table
aws ec2 describe-route-tables \
  --filters "Name=association.subnet-id,Values=<private-subnet-id>" \
  --query 'RouteTables[0].Routes'
```

**Common causes:**
1. NAT gateway not created
2. NAT gateway in wrong availability zone
3. Route table not updated to point to NAT
4. NAT gateway elastic IP exhausted

**Fixes:**
- Create NAT gateway in public subnet
- Add route `0.0.0.0/0 -> nat-<id>` to private subnet route table
- Use one NAT per AZ for high availability
- Check NAT gateway CloudWatch metrics for errors

---

## DNS Resolution

### Symptom: "Could not resolve host" errors

**Diagnosis:**
```bash
# Test DNS from container
nslookup bedrock.us-east-1.amazonaws.com
dig bedrock.us-east-1.amazonaws.com

# Check VPC DNS settings
aws ec2 describe-vpc-attribute \
  --vpc-id <vpc-id> \
  --attribute enableDnsSupport

aws ec2 describe-vpc-attribute \
  --vpc-id <vpc-id> \
  --attribute enableDnsHostnames
```

**Fixes:**
- Enable DNS support on VPC: `enableDnsSupport = true`
- Enable DNS hostnames: `enableDnsHostnames = true`
- Check if custom DHCP options set overrides DNS
- Verify Route 53 resolver rules if using private hosted zones

---

## Endpoint Configuration

### Symptom: Slow API calls or want to avoid internet routing

**VPC endpoints for AgentCore:**
```bash
# Create Bedrock endpoint
aws ec2 create-vpc-endpoint \
  --vpc-id <vpc-id> \
  --service-name com.amazonaws.us-east-1.bedrock-runtime \
  --vpc-endpoint-type Interface \
  --subnet-ids <subnet-id> \
  --security-group-ids <sg-id>

# Create S3 gateway endpoint (for model artifacts)
aws ec2 create-vpc-endpoint \
  --vpc-id <vpc-id> \
  --service-name com.amazonaws.us-east-1.s3 \
  --vpc-endpoint-type Gateway \
  --route-table-ids <rtb-id>
```

**Recommended endpoints:**
- `com.amazonaws.<region>.bedrock-runtime` (model invocation)
- `com.amazonaws.<region>.s3` (artifacts, logs)
- `com.amazonaws.<region>.logs` (CloudWatch)
- `com.amazonaws.<region>.monitoring` (CloudWatch metrics)
- `com.amazonaws.<region>.sts` (credential management)

---

## TLS/Certificate Errors

### Symptom: SSL/TLS handshake failure

**Diagnosis:**
```bash
# Test TLS connection
openssl s_client -connect api.example.com:443 -servername api.example.com

# Check certificate chain
curl -vI https://api.example.com 2>&1 | grep -A 5 "SSL certificate"
```

**Common causes:**
1. Expired certificate
2. Self-signed certificate not trusted
3. Certificate hostname mismatch
4. Old TLS version (< 1.2)

**Fixes:**
- Update CA certificates in container: `apt-get update && apt-get install ca-certificates`
- For self-signed certs: add to trust store or set `REQUESTS_CA_BUNDLE`
- Ensure TLS 1.2+ is required (AWS APIs require it)
- Don't disable certificate verification in production
