# Sample story: Manage tasks

## User story

As an authenticated user, I want to create, view, and update tasks so that I can keep track of my work.

## Acceptance criteria

1. A user can create a task by providing a title and status. A successful creation returns the created task.
2. A task title must contain 1 to 100 characters.
3. A user can retrieve an existing task by its task ID. The response contains the task ID, title, status, and creation time.
4. Requesting a task ID that does not exist returns a not-found response.
5. A user can update a task's title, description, status, or due date.

## Business context

This sample is for testing the Requirement Review Agent, API Contract Agent, and Test Case Generation Agent together. The matching OpenAPI file is `task-api.openapi.yaml`.

## Dependencies

No external service or integration architecture is specified. The API base URL in the OpenAPI file is an example and is not a live test target.

## Deliberate clarification points

- The story allows titles up to 100 characters while the OpenAPI schema allows up to 120.
- The OpenAPI file declares a 400 response for invalid create requests but does not define its response body schema.
- The update request body is required, but the OpenAPI schema does not say whether an empty object is accepted.
- The story does not define how invalid dates or unsupported status values are reported.
