---
title: Docker
---
# Docker

Docker builds and runs containers from images. A Dockerfile describes the build,
and Docker Compose defines services, networks, health checks, and persistent
volumes for a multi-container application. Containers share the host kernel but
run with isolated processes and filesystems.

Use small base images, pin important dependencies, and run application processes
as a non-root user. Keep secrets out of image layers and pass configuration at
runtime. A health check reports whether a service is ready; a restart policy can
recover from some process failures.
