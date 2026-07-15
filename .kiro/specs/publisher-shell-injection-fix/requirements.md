# Requirements Document

## Introduction

`PublisherAgent` builds git command strings from ticket data (title, id) and workflow rules pulled from vault notes, then executes them with `subprocess.run(cmd, shell=True, ...)`. Because ticket titles and rule-derived values flow unsanitized into a shell-interpreted command string, a crafted ticket title or commit pattern can inject arbitrary shell commands during the git publishing workflow. This feature replaces shell-based git execution with list-based `subprocess.run` calls, sanitizes ticket titles into safe branch-name slugs, and strips control characters and newlines from commit messages, while preserving the existing `results["operations"]` structure and stop-on-first-failure behavior.

## Glossary

- **Publisher_Agent**: The `PublisherAgent` class in `autopilot/infrastructure/agents/publisher.py` responsible for executing the git publishing workflow.
- **Git_Command_Executor**: The internal routine (currently `_git_cmd`) that runs a single git operation and records its result.
- **Branch_Slug**: A sanitized string derived from a ticket title, composed only of lowercase alphanumeric characters and hyphens, used to build branch names.
- **Commit_Message**: The text passed to `git commit -m` after control characters and newlines have been removed.
- **Operations_Log**: The list stored at `results["operations"]`, where each entry records a command's argument list, success flag, and output.
- **Git_Workflow_Step**: One discrete git operation in the publishing sequence (checkout source, pull, checkout new branch, add, commit, push).

## Requirements

### Requirement 1: List-based subprocess execution

**User Story:** As a developer maintaining Autopilot, I want git commands executed without shell interpretation, so that ticket data cannot be used to inject arbitrary shell commands.

#### Acceptance Criteria

1. THE Git_Command_Executor SHALL invoke `subprocess.run` with `shell=False` and a single list of string arguments, where the first element is the literal executable name `"git"` and each subcommand, flag, and value (e.g. branch name, remote name, commit message) is its own separate list element.
2. THE Publisher_Agent SHALL construct each Git_Workflow_Step as a list of string arguments and SHALL NOT concatenate any argument values into a single shell-interpreted string before passing them to the Git_Command_Executor.
3. WHEN the Git_Command_Executor records a Git_Workflow_Step in the Operations_Log, THE Git_Command_Executor SHALL store the "command" field as the exact list of string arguments that was executed, without joining or re-serializing it into a single string.
4. THE Publisher_Agent SHALL NOT pass the `shell=True` argument to any `subprocess.run` call.

### Requirement 2: Branch name sanitization

**User Story:** As a developer maintaining Autopilot, I want ticket titles converted into safe branch-name slugs, so that special characters in a ticket title cannot alter or escape the intended git command.

#### Acceptance Criteria

1. WHEN the Publisher_Agent derives a Branch_Slug from a ticket title, THE Publisher_Agent SHALL convert all uppercase ASCII letters in the ticket title to lowercase before applying any other sanitization rule.
2. WHEN the lowercased ticket title contains a character that is not a lowercase ASCII letter, digit, space, or hyphen, THE Publisher_Agent SHALL replace that character with a hyphen when producing the Branch_Slug.
3. WHEN the Branch_Slug (after character replacement) contains two or more consecutive space or hyphen characters in any combination, THE Publisher_Agent SHALL collapse the sequence to a single hyphen.
4. WHEN a produced Branch_Slug begins or ends with a hyphen, THE Publisher_Agent SHALL trim the leading and trailing hyphens.
5. IF a ticket title produces an empty Branch_Slug after sanitization, THEN THE Publisher_Agent SHALL substitute a fallback slug value of "implementation".
6. THE Publisher_Agent SHALL limit the Branch_Slug to 30 Unicode code points, measured after all other sanitization rules have been applied.
7. IF truncating the Branch_Slug to 30 Unicode code points results in a trailing hyphen, THEN THE Publisher_Agent SHALL trim that trailing hyphen.

### Requirement 3: Commit message sanitization

**User Story:** As a developer maintaining Autopilot, I want commit messages stripped of control characters and newlines, so that ticket data cannot inject additional git command-line arguments or break out of the intended commit message.

#### Acceptance Criteria

1. WHEN the Publisher_Agent builds the fully formatted Commit_Message (after applying the configured commit pattern to the ticket id and title), THE Publisher_Agent SHALL remove all U+000A (line feed) and U+000D (carriage return) characters from the Commit_Message.
2. WHEN the Publisher_Agent builds the fully formatted Commit_Message, THE Publisher_Agent SHALL remove all characters in the Unicode ranges U+0000–U+001F and U+007F from the Commit_Message, except that it SHALL preserve the space character (U+0020).
3. IF removing newline and control characters results in an empty or whitespace-only Commit_Message, THEN THE Publisher_Agent SHALL substitute a fallback Commit_Message value of "Automated commit".
4. THE Publisher_Agent SHALL pass the Commit_Message to `git commit` as a distinct argument-list element, separate from the `-m` flag.

### Requirement 4: Stop-on-failure git workflow

**User Story:** As a developer running Autopilot, I want the git publishing workflow to stop at the first failed step, so that Autopilot does not attempt further git operations against an inconsistent repository state.

#### Acceptance Criteria

1. IF a Git_Workflow_Step returns a non-zero exit code, THEN THE Publisher_Agent SHALL append an Operations_Log entry with "success" set to `false` for that step and SHALL NOT execute any subsequent Git_Workflow_Steps.
2. IF a Git_Workflow_Step raises an exception during execution, THEN THE Publisher_Agent SHALL catch the exception, append an Operations_Log entry with "success" set to `false` and "output" populated with a text description of the exception, and SHALL NOT execute any subsequent Git_Workflow_Steps.
3. IF the git publishing workflow stops due to a failed Git_Workflow_Step, THEN THE Publisher_Agent SHALL return normally (without raising or propagating the failure) with an Operations_Log containing only the steps attempted up to and including the failed step.

### Requirement 5: Preserved operations structure

**User Story:** As a developer relying on Publisher output, I want the existing `results["operations"]` structure preserved, so that downstream code consuming publishing results continues to work without modification.

#### Acceptance Criteria

1. THE Publisher_Agent SHALL return a results dictionary containing an "operations" key whose value is a list.
2. WHEN the Git_Command_Executor records a Git_Workflow_Step, THE Git_Command_Executor SHALL append an entry to the Operations_Log containing "command", "success", and "output" fields, where "command" is the argument list defined in Requirement 1.
3. THE Publisher_Agent SHALL populate the "success" field with a boolean value reflecting whether the Git_Workflow_Step's exit code was zero.
4. THE Publisher_Agent SHALL populate the "output" field with the captured standard output or standard error text produced by the Git_Workflow_Step.
5. WHEN the Branch_Slug and branch name have been computed, THE Publisher_Agent SHALL populate the "branch" field in the results dictionary, regardless of whether subsequent Git_Workflow_Steps succeed.
6. WHEN a Git_Workflow_Step raises an exception rather than returning an exit code, THE Publisher_Agent SHALL populate that step's "success" field with `false` and its "output" field with a text description of the exception, consistent with Requirement 4.
7. WHEN the commit Git_Workflow_Step has been attempted, THE Publisher_Agent SHALL populate the "commit_message" field in the results dictionary with the sanitized Commit_Message.
8. IF the git publishing workflow stops before the commit Git_Workflow_Step is attempted, THEN THE Publisher_Agent SHALL omit the "commit_message" field from the results dictionary.
