# Server snapshot, 31 October 2026

Read-only capture of the running `/opt/allsewpattern` deployment.

- `source.tar.gz`: 148 source/configuration-template/test files copied from the server.
- `active-build.tar.gz`: the active frontend index and the JavaScript/CSS files it references.

The server's `REVISION` contains `f7a6e37cd9f527d74fe7136d837979739d68bdae`.
The backend source files match that Git revision. The loose frontend sources on
the server are older than both the active compiled UI and Git main. In particular,
the active bundle includes analytics, avatar management, manufacturer naming and
scroll-to-top functionality that the loose Vue source files omit.

These archives preserve the server as found, including that inconsistency.
Do not replace main's frontend sources with the archived loose files: doing so
would remove active functionality. Main remains the maintained source checkout.
The active bundle is preserved as evidence, not as a replacement for a Vite build.

Excluded: `.env`, runtime database/data/media, virtual environments, caches,
node_modules, old compiled bundles and temporary release directories. No server
services, configuration or application data were changed during capture.
