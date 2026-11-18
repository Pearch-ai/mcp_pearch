# Repository Guidelines

## Branches and Worktrees

Make changes on the repository's `main` branch (or `master` if that is its primary branch) unless the user explicitly asks for a feature branch or the context clearly indicates that the fixes belong on a release branch. Do not create a release branch unless explicitly requested. If the user asks for a pull request, move the relevant changes to a feature branch and create the PR.

When a deployment would use a feature branch, tell the user that deploying from it is discouraged. Recommend merging the changes into `main` or the intended release branch, then deploying from that branch.
