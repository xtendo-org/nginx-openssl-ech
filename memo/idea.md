[Encrypted Client Hello](https://datatracker.ietf.org/doc/draft-ietf-tls-esni/) is a nice step forward, for privacy and security of the Internet.

As of writing this memo (2026-01-03), it is already supported by major web browsers like:

- Firefox, added in version 118 and enabled in 119 [^1] released on 2023-10-24 [^2]
- Chromium, since version 117 [^3] marked as stable on 2023-09-12 [^4]

However, [Nginx started its ECH support in 1.29.4](https://blog.nginx.org/blog/nginx-open-source-1-29-3-and-1-29-4), which was released on 2025-12-10 (less than a month ago, as of writing). Plus, it requires a **manual build**, because _OpenSSL's ECH support is still in a feature branch_. Nginx's release note says:

> ECH is expected to be included in OpenSSL 4.0 (anticipated April 2026)

(This matches the "milestone" shown in OpenSSL's GitHub repo. [^5])

I wanted to try this out.

[OhMyECH](https://addons.mozilla.org/en-US/firefox/addon/oh-my-ech/) shows a green padlock when you visit <https://tls-ech.dev>. I'd like to see that on my tiny web server too. The trouble is, my Raspberry Pi server has such a limited computing power, and I fear the build will take too long, especially if I might need to do it repeatedly. The idea is, in GitHub Actions:

- Obtain the source code:
    - Nginx 1.29.4
    - OpenSSL's ECH-support branch
    - Brotli support ([ngx_brotli](https://github.com/google/ngx_brotli))
- **Merge** OpenSSL's 3.6 release and the ECH feature branch (!)
- Build, targeting "Linux + arm64". Statically link everything except glibc. Make one single binary executable file.
- Pick up the binary and add it to this repo as a release asset file

Privacy and security right now!

[^1]: https://support.mozilla.org/en-US/kb/understand-encrypted-client-hello
[^2]: https://www.firefox.com/en-US/firefox/119.0/releasenotes/
[^3]: https://chromestatus.com/feature/6196703843581952
[^4]: https://chromereleases.googleblog.com/2023/09/stable-channel-update-for-desktop_12.html
[^5]: https://github.com/openssl/openssl/milestone/55
