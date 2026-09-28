# GitHub setup checklist

The local project is ready for a public repository named `the-40075-project`. Complete these steps in order so the first pushed workflow can sync and deploy successfully.

1. On GitHub, create an empty **public** repository named `the-40075-project`. Do not initialize it with a README, license, or `.gitignore`.

2. Before pushing code, open **Settings → Secrets and variables → Actions → New repository secret**. Create a secret named `CONCEPT2_TOKEN` and paste the Concept2 personal API token as its value.

3. Open **Settings → Actions → General → Workflow permissions** and select **Read and write permissions**. This permits the workflow's narrowly scoped `data/archive/` commit. The workflow itself refuses to stage other paths.

4. Open **Settings → Pages → Build and deployment** and choose **GitHub Actions** as the source.

5. In the local project, inspect what will be committed. The token, generated site, lock file, and recovery files must remain ignored:

   ```sh
   git status --short
   git status --short --ignored
   ```

6. Add the GitHub remote, replacing `YOUR-GITHUB-NAME` with the account or organization that owns the repository:

   ```sh
   git remote add origin git@github.com:YOUR-GITHUB-NAME/the-40075-project.git
   ```

7. Make the initial commit and push yourself:

   ```sh
   git add .
   git commit -m "Create the 40075 km rowing tracker"
   git push -u origin main
   ```

8. Open the repository's **Actions** tab. The initial push starts **Sync Concept2 and deploy Pages**. After it succeeds, the deployment URL appears in the workflow's `deploy` job and under **Settings → Pages**.

9. Use **Actions → Sync Concept2 and deploy Pages → Run workflow** whenever an immediate remote refresh is wanted. Leave **Full reconciliation** off for a normal incremental refresh; enable it only when a complete comparison is desired.

The scheduled workflow checks every six hours at 17 minutes past the UTC hour. No-op checks do not create commits. Successful activity changes produce a bot commit containing only `data/archive/` files and deploy the newly generated site. GitHub-token bot pushes do not start a duplicate workflow; the run that made the commit performs the deployment itself.

The initial GitHub Pages address will have the form `https://YOUR-GITHUB-NAME.github.io/the-40075-project/`. The custom `row.islandinamber.com` domain can be connected later.
