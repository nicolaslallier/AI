# Working with Cursor AI

## Overview

This project includes a comprehensive `.cursorrules` file that configures the Cursor AI assistant to act as an expert Vue 3 developer with strict coding standards.

## AI Assistant Persona

### Developer Profile
- **Experience Level**: Expert Vue.js/TypeScript developer
- **Communication Style**: Technical and precise with detailed explanations
- **Proactiveness**: Very proactive with improvement suggestions
- **Code Style**: Always enforces coding standards automatically
- **Testing**: Strict TDD approach - always creates tests with code
- **Documentation**: Full JSDoc documentation required
- **Refactoring**: Immediate refactoring to match best practices

### Priority Order
1. **Correctness** - Bug-free code
2. **Maintainability** - Clean, understandable code
3. **Performance** - Optimized solutions
4. **Testability** - Comprehensive test coverage

## What the AI Will Do

### Automatic Behaviors

**Code Generation:**
- Uses kebab-case for component files
- Uses Composition API (standard `<script>`, not `<script setup>`)
- Single quotes, semicolons, 120 char lines
- Strict import ordering
- Comprehensive JSDoc comments
- Full error handling
- Creates tests alongside implementation

**Code Review:**
- Points out violations of coding standards
- Suggests performance optimizations
- Identifies potential bugs and edge cases
- Recommends better TypeScript types
- Highlights missing tests or documentation

**Refactoring:**
- Automatically refactors code to match standards
- Explains what was improved and why
- Ensures no functionality is broken
- Adds missing error handling
- Improves naming for clarity

## How to Work with the AI

### Asking Questions

**Good Questions:**
```
"How should I structure a new feature for user authentication?"
"What's the best way to handle form validation following our standards?"
"Can you review this component for SOLID principle violations?"
```

**Questions to Avoid:**
```
"Make it work" (too vague)
"Fix the bug" (need specifics)
"Add a feature" (need requirements)
```

### Requesting Code

**Effective Requests:**
```
"Create a composable for fetching and caching user data with:
- Error handling for network failures
- Loading states
- TypeScript types
- Unit tests
- JSDoc documentation"
```

**Less Effective:**
```
"Create a user composable" (too vague)
```

### Code Reviews

The AI will automatically:
- Check for coding standard violations
- Verify SOLID principles are followed
- Ensure tests are present
- Validate JSDoc documentation
- Review error handling
- Check TypeScript strictness

## Understanding AI Responses

### Response Structure

1. **Explanation** - Reasoning behind the approach
2. **Code** - Complete, production-ready implementation
3. **Tests** - Corresponding test files
4. **Documentation** - JSDoc and inline comments
5. **Trade-offs** - Alternative approaches and why this was chosen

### Example Response Format

```
I'll create a counter composable following these principles:
- Single Responsibility: Only manages counter state
- Dependency Inversion: Depends on store abstraction
- Comprehensive error handling for range violations
- Full test coverage

Here's the implementation:
[Code with full JSDoc]

Here are the tests:
[Complete test suite]

Trade-offs:
- Used Pinia store for persistence vs local ref for simplicity
- Chose to validate range to prevent overflow
- Made increment/decrement amount optional for flexibility
```

## Customizing AI Behavior

The `.cursorrules` file can be modified to adjust:

- Communication style
- Proactiveness level
- Code explanation detail
- Testing approach
- Error handling strictness
- Documentation requirements

## Common Workflows

### 1. Creating a New Feature

```
You: "I need to create a user profile feature"

AI: [Asks clarifying questions about requirements]

You: [Provides details]

AI: [Creates complete feature with:
- Component structure
- Composables
- Store
- Types
- Tests
- Documentation]
```

### 2. Refactoring Existing Code

```
You: "Review and refactor src/components/old-component.vue"

AI: [Analyzes code, identifies issues]
AI: [Provides refactored version with explanations]
AI: [Adds missing tests and documentation]
```

### 3. Debugging

```
You: "This component isn't updating when the store changes"

AI: [Analyzes the issue]
AI: [Explains the problem]
AI: [Provides corrected code]
AI: [Adds tests to prevent regression]
```

## Best Practices for AI Collaboration

### Do:
✅ Provide clear requirements and context
✅ Ask for explanations of decisions
✅ Request alternative approaches
✅ Ask about trade-offs
✅ Request specific examples
✅ Ask for test coverage

### Don't:
❌ Accept code without understanding it
❌ Skip reading the explanations
❌ Ignore suggested improvements
❌ Bypass testing requirements
❌ Remove error handling for simplicity
❌ Ignore TypeScript errors

## Learning from the AI

### Study the Patterns

When the AI generates code, notice:
- How it structures components
- How it handles errors
- How it writes tests
- How it documents code
- How it applies SOLID principles

### Ask "Why?"

```
You: "Why did you structure it this way?"
AI: [Explains design decisions and alternatives]

You: "What are the trade-offs?"
AI: [Discusses pros/cons of the approach]
```

## Troubleshooting

### AI Generates Code That Doesn't Match Standards

**Cause**: May have missed context from .cursorrules
**Solution**: Explicitly mention "following our coding standards"

### AI is Too Verbose

**Cause**: Configured for detailed explanations
**Solution**: Ask for "concise implementation" or adjust .cursorrules

### AI Doesn't Create Tests

**Cause**: Not explicitly requested
**Solution**: Always mention "with tests" or check .cursorrules

## Advanced Usage

### Custom Prompts

Create prompt templates for common tasks:

```
"Create a new feature following our architecture:
- Feature name: [NAME]
- Description: [DESC]
- Include: components, composables, store, types, tests, docs
- Follow: SOLID principles, TDD, coding standards"
```

### Multi-File Operations

```
You: "Refactor the entire counter feature to use a different state management approach"

AI: [Updates multiple files consistently]
AI: [Ensures all tests still pass]
AI: [Updates documentation]
```

## Integration with Development Workflow

### Pre-Commit
Use AI to review code before committing:
```
You: "Review my changes for commit"
AI: [Checks standards, tests, documentation]
```

### Code Review
Get AI perspective before PR:
```
You: "Review this PR for potential issues"
AI: [Identifies problems, suggests improvements]
```

### Pair Programming
Work iteratively with AI:
```
You: "Let's build a login form step by step"
AI: [Works through each piece with explanations]
```

## Resources

- `.cursorrules` - Full AI configuration
- [Coding Standards](./CODING_STANDARDS.md) - Referenced by AI
- [TDD Guide](./TDD_GUIDE.md) - Testing approach AI follows
- [SOLID Principles](./SOLID_PRINCIPLES.md) - Architecture AI enforces

## Feedback

If the AI's behavior needs adjustment:
1. Modify `.cursorrules` file
2. Be explicit in prompts about desired behavior
3. Provide examples of what you want
4. Reference specific documentation

The AI is a tool to enhance productivity while maintaining high code quality. Use it as a knowledgeable pair programmer who enforces best practices.

