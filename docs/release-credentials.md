# Release credentials

What to obtain before a signed, notarized build is possible, and where each
piece goes. One-time setup, apart from the certificate's annual renewal.

Everything here is Apple's, and its only job is making macOS trust a downloaded
app. Luminary has no auto-updater, so no signing key of our own is involved.

## 1. Apple Developer Program

Enrol at <https://developer.apple.com/programs/>. $99/year, Apple ID with
two-factor required. Approval is usually same-day but can take longer for
organizations.

## 2. Developer ID Application certificate

Xcode is not required; the certificate can be requested with Keychain Access.

1. **Keychain Access → Certificate Assistant → Request a Certificate From a
   Certificate Authority.** Enter your email and name, select **Saved to disk**
   and **Let me specify key pair information**. Choose 2048 bits / RSA. This
   writes `CertificateSigningRequest.certSigningRequest`.
2. At <https://developer.apple.com/account/resources/certificates> choose **+**,
   then **Developer ID Application** (not "Mac Development" and not "Developer
   ID Installer"). Upload the CSR and download the resulting `.cer`.
3. Double-click the `.cer` to add it to your login keychain.
4. Confirm it is usable:

   ```bash
   security find-identity -v -p codesigning
   # Developer ID Application: Your Name (ABCDE12345)
   ```

   The 10-character suffix is your **Team ID**.

5. Export for CI: in Keychain Access select the certificate *and* its private
   key, **File → Export Items**, save as `.p12`, and set a password. That
   password becomes `APPLE_CERTIFICATE_PASSWORD`.

## 3. App Store Connect API key

Used by `notarytool`. It must be a **Team key** — personal keys are rejected by
the Notary API.

1. <https://appstoreconnect.apple.com> → **Users and Access** → **Integrations**
   → **App Store Connect API** → **Team Keys**.
2. **+**, name it, set access to **Developer**, generate.
3. Download `AuthKey_XXXXXXXXXX.p8`. **This download is offered once.** Store it
   somewhere durable, e.g. `~/private_keys/`.
4. Record the **Key ID** (in the filename and the table) and the **Issuer ID**
   (shown above the key list, a UUID).

## 4. Not needed yet: the updater key

Luminary ships as a downloaded DMG with no auto-updater, so nothing here
requires a Tauri signing key.

If you add one later, generate it once with
`node_modules/.bin/tauri signer generate -w ~/.tauri/luminary.key`, commit the
public key to `tauri.conf.json`, and keep the private key as a CI secret.
**Back it up**: losing it means no installed copy can ever be updated, since a
new key is a new identity that shipped copies will reject.

## 5. Test locally before touching CI

Faster feedback than a workflow run, and it uses the same scripts.

```bash
export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (ABCDE12345)"
export APPLE_TEAM_ID=ABCDE12345
export APPLE_API_KEY_PATH=~/private_keys/AuthKey_XXXXXXXXXX.p8
export APPLE_API_KEY_ID=XXXXXXXXXX
export APPLE_API_ISSUER=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
APP=src-tauri/target/release/bundle/macos/Luminary.app
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' backend/pyproject.toml | head -1)

make stage
make desktop-app
bash scripts/macos/sign.sh          "$APP"
bash scripts/macos/verify_signed.sh "$APP"
bash scripts/macos/dmg.sh           "$APP" "$VERSION"
bash scripts/macos/notarize.sh "build/dist/Luminary_${VERSION}_aarch64.dmg" "$APP"
```

Expect the notary submission to take 10–30 minutes; it scales with file count
and this bundle holds ~55k files. On rejection, `build/dist/notary-log.json`
names the offending path.

The end state to check:

```bash
spctl --assess --type exec --verbose=4 "$APP"
# ...: accepted
# source=Notarized Developer ID
```

## 6. Provision CI

```bash
base64 -i /path/to/cert.p12                 | gh secret set APPLE_CERTIFICATE
base64 -i ~/private_keys/AuthKey_XXX.p8     | gh secret set APPLE_API_KEY
gh secret set APPLE_CERTIFICATE_PASSWORD
gh secret set APPLE_SIGNING_IDENTITY
gh secret set APPLE_TEAM_ID
gh secret set APPLE_API_KEY_ID
gh secret set APPLE_API_ISSUER
gh secret set KEYCHAIN_PASSWORD                 # any random string
```

Then tag a release; `.github/workflows/release-macos-app.yml` does the rest.

## Renewal

Apple issues Developer ID certificates for a term of up to five years, but a
much shorter one is possible. Read the expiry off the certificate rather than
assuming it:

```bash
security find-certificate -c "Developer ID Application" -p login.keychain \
  | openssl x509 -noout -enddate
```

Renewing means a new certificate, so `APPLE_CERTIFICATE` and
`APPLE_CERTIFICATE_PASSWORD` must be re-exported and re-set.

The Apple Developer Program membership renews annually. An expired membership
does not invalidate already notarized builds, but no new ones can be produced
until it is renewed.
