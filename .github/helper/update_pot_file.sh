#!/bin/bash
set -e
cd ~ || exit

echo "Setting Up Bench..."

pip install creqit-bench
bench -v init creqit-bench --skip-assets --skip-redis-config-generation --python "$(which python)" --creqit-path "${GITHUB_WORKSPACE}"
cd ./creqit-bench || exit

echo "Generating POT file..."
bench generate-pot-file --app creqit

cd ./apps/creqit || exit

echo "Configuring git user..."
git config user.email "developers@creqit.com"
git config user.name "creqit-pr-bot"

echo "Setting the correct git remote..."
# Here, the git remote is a local file path by default. Let's change it to the upstream repo.
git remote set-url upstream https://github.com/creqit/creqit.git

echo "Creating a new branch..."
isodate=$(date -u +"%Y-%m-%d")
branch_name="pot_${BASE_BRANCH}_${isodate}"
git checkout -b "${branch_name}"

echo "Commiting changes..."
git add creqit/locale/main.pot
git commit -m "chore: update POT file"

gh auth setup-git
git push -u upstream "${branch_name}"

echo "Creating a PR..."
gh pr create --fill --base "${BASE_BRANCH}" --head "${branch_name}" -R creqit/creqit
