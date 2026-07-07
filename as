create a github workflow, it shoould do the below
1. find the list of files changed
2. identify if the changes are in any of the dbt models from the current repo
3. if there are any models, it should fetch the complte node details
4. for each model, find if the changes are
  a. in the sql select columns only, get the list of columns that are changed(addition, modification, removal)
  b. other than columns of the sql
  c. both a & b
5. put a pr comment with details like
  1. model name
  2. type of change
  3. column names where applicable


