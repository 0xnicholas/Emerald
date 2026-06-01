# Emerald K8s Manifests

Production-ready Kubernetes manifests for Emerald deployment.

## Prerequisites

- Kubernetes 1.28+
- Ingress controller (nginx recommended)
- PersistentVolume provisioner for PostgreSQL, Neo4j, Redis, MinIO
- cert-manager (for TLS, optional)

## Quick Start

```bash
# 1. Create namespace and secrets
kubectl apply -f namespace.yaml
kubectl apply -f secret.yaml   # EDIT secret.yaml first!
kubectl apply -f configmap.yaml

# 2. Deploy dependencies (PostgreSQL, Neo4j, Redis, MinIO)
# Use Helm or your own manifests. Example with Helm:
helm install postgres oci://registry-1.docker.io/bitnamicharts/postgresql \
  --namespace emerald --set auth.database=emerald

# 3. Deploy Emerald
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
kubectl apply -f ingress.yaml
kubectl apply -f hpa.yaml

# 4. Verify
kubectl get pods -n emerald
kubectl logs -n emerald -l app=emerald-api --tail=50
```

## Files

| File | Purpose |
|---|---|
| `namespace.yaml` | emerald namespace |
| `configmap.yaml` | Non-sensitive configuration |
| `secret.yaml` | Sensitive values (EDIT BEFORE APPLY) |
| `deployment.yaml` | API, Worker, Beat deployments |
| `service.yaml` | ClusterIP service for API |
| `ingress.yaml` | nginx ingress with rate limiting |
| `hpa.yaml` | Horizontal Pod Autoscaler (2-10 replicas) |
| `backup-cronjob.yaml` | Daily PostgreSQL backup at 2 AM |

## Scaling

```bash
# Manual scale
kubectl scale deployment emerald-api --replicas=5 -n emerald

# View HPA status
kubectl get hpa -n emerald
```
