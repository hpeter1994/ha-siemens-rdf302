# Publishing checklist

Nothing here has been done yet. Requirements come from the [HACS publishing docs](https://www.hacs.xyz/docs/publish/integration/) and the [HACS default store rules](https://www.hacs.xyz/docs/publish/include/).

## Before the first upload

- [ ] Confirm that the MIT license suits you.
- [ ] Decide whether to publish `docs/manuals`. The Siemens notice allows distribution only with their express permission, so a takedown request is possible. Removing the folder later does not remove it from git history.
- [ ] Confirm that `git status` doesn't list `hardware_tests/`. It is git-ignored.
- [ ] Search the files for private network addresses and hostnames.

## Create the repository

- [ ] Create a public repository named `ha-siemens-rdf302`.
- [ ] Add a description, for example "Home Assistant integration for Siemens RDF302 thermostats over Modbus TCP (written by AI)".
- [ ] Add topics: `home-assistant`, `hacs`, `hacs-integration`, `modbus`, `thermostat`, `siemens`.
- [ ] Leave issues enabled.
- [ ] Push, and wait for the **Validate** and **Tests** workflows to pass.

## Use as a HACS custom repository

This works as soon as the repository is public. Add its URL in HACS under **Custom repositories**, with the type **Integration**.

## Submit to the HACS default store (optional)

- [ ] Make sure the HACS and Hassfest actions pass with no errors or ignores.
- [ ] After they pass, create a full GitHub release, not just a tag, such as `v0.1.0`. Its version should match `manifest.json`.
- [ ] Open a pull request to [hacs/default](https://github.com/hacs/default), adding the repository to the `integration` file in alphabetical order. It must come from your personal account, not an organization.

## For each later release

- [ ] Update `version` in `manifest.json`.
- [ ] Wait for the workflows to pass.
- [ ] Create a GitHub release with that version.
