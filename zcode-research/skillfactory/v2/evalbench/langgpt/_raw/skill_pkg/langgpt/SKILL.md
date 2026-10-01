---
name: langgpt
description: "LangGPT structured prompt design framework assistant. Helps create high-quality prompts using structured templates with Role, Profile, Skills, Rules, Workflow sections. This skill should be used when writing or optimizing prompts for large language models, converting traditional prompts to structured format, or designing AI personas and roles."
---

# LangGPT - Structured Prompt Design Framework

## Overview

LangGPT is a structured, template-based prompt design methodology that enables creation of high-quality prompts for large language models. Think of it as a "programming language for prompts" - systematic, reusable, and infinitely scalable.

## When to Use This Skill

- Writing new prompts for LLMs (ChatGPT, Claude, etc.)
- Optimizing existing prompts for better performance
- Converting traditional prompts to structured format
- Designing AI roles, personas, or expert systems
- Creating reusable prompt templates

## Core Template Structure

The fundamental LangGPT template uses Markdown hierarchy:

```markdown
# Role: Your_Role_Name

## Profile
- Author: YourName
- Version: 1.0
- Language: English
- Description: Clear role description and core capabilities

## Goal
- Outcome: What concrete result should be delivered
- Done Criteria: Clear acceptance criteria
- Non-Goals: What is explicitly out of scope

### Skill-1
1. Specific skill description
2. Expected behavior and output

### Skill-2
1. Specific skill description
2. Expected behavior and output

## Rules
1. Don't break character under any circumstance
2. Don't make up facts or hallucinate

## Workflow
1. Analyze user input and identify intent
2. Apply relevant skills systematically
3. Deliver structured, actionable output

## Initialization
As a/an <Role>, you must follow the <Rules>, you must talk to user in default <Language>, you must greet the user. Then introduce yourself and introduce the <Workflow>.
```

## Key Concepts

### 1. Structural Identifiers

| Symbol | Purpose | Example |
|--------|---------|---------|
| `#` | Level 1 title (global scope) | `# Role: Expert` |
| `##` | Level 2 title (section scope) | `## Profile` |
| `###` | Level 3 title (subsection) | `### Skill-1` |
| `<>` | Variables for references | `<Role>`, `<Rules>` |
| `-` | List items | `- Author: YZFly` |

### 2. Core Attribute Words

| Attribute | Purpose |
|-----------|---------|
| **Role** | Role name/title - activates role-playing capability |
| **Profile** | Identity and capabilities resume |
| **Goal** | Desired outcome, done criteria, and non-goals |
| **Skills** | Specific abilities the role possesses |
| **Rules** | Boundaries and constraints to follow |
| **Workflow** | Step-by-step interaction logic |
| **Initialization** | Opening message and setup behavior |

### 3. Variables

Variables enable self-referential prompts using `<Variable>` syntax:

```markdown
As a/an <Role>, you must follow <Rules> and communicate in <Language>
```

### 4. Commands

Define reusable user-triggered actions:

```markdown
## Commands
- Prefix: "/"
- Commands:
    - help: Display all available commands
    - continue: Resume interrupted output
    - improve: Enhance current response
```

### 5. Reminders

Combat context loss in long conversations:

```markdown
## Reminder
1. Always check role settings before responding
2. Current language: <Language>, Active rules: <Rules>
```

## Workflow for Creating Prompts

### Step 1: Define the Role
Set a clear role name that activates model capabilities:
- Use specific expert titles: "FitnessGPT", "Code Expert", "Data Analyst"
- Alternative: Use `Expert` or `Master` for domain expertise

### Step 2: Write the Profile
Include:
- Author and version for tracking
- Target language
- Concise description of the role's characteristics

### Step 3: Define Skills
Break down the role's capabilities into specific, actionable skills with detailed descriptions.

### Step 4: Establish Rules
Set constraints the model must follow:
- Content restrictions
- Behavior guidelines
- Output format requirements

### Step 5: Design Workflow
Create a logical step-by-step process for how the role should handle user requests.

### Step 6: Set Initialization
Define how the role should introduce itself and begin interaction.

## Advanced Techniques

### Conditional Logic

```markdown
If user provides [code], then analyze and suggest improvements
Else if user asks [question], then provide detailed explanation
Else, prompt for clarification
```

### Output Format Control

Add an OutputFormat section when specific formatting is needed:

```markdown
## OutputFormat
- Use markdown headers for sections
- Include code blocks with language specification
- End with actionable next steps
```

### Multi-Format Support

While Markdown is recommended, LangGPT supports JSON/YAML for programmatic use:

```yaml
role: DataAnalyst
profile:
  version: "2.0"
  language: "Python"
skills:
  - statistical_analysis
  - data_visualization
```

## Templates

Reference templates are available in `references/templates.md`:
- Basic Role Template
- Expert Template (for GPT-3.5)
- AutoGPT-style Template

## Examples

Reference example prompts in `references/examples.md`:
- FitnessGPT - Personalized diet and workout planner
- Chinese Poet - Classical poetry composer
- Xiaohongshu Master - Social media viral content creator
- Name Master - Chinese name creator from classical poetry
- DecisionGPT - Rational decision-making helper
- CAN - Expert coding assistant
- Data Analyst - Professional data analysis

## Best Practices

1. **Build Global Chain of Thought**: Structure sections in logical order (Role → Profile → Skills → Rules → Workflow → Initialization)

2. **Maintain Semantic Consistency**:
   - Use consistent identifier formatting
   - Match attribute words with their content

3. **Combine with Other Techniques**: Integrate CoT, ToT, few-shot examples as needed

4. **Iterate and Optimize**: Start with auto-generated prompts, then manually refine based on performance

## Model Compatibility

| Model | Performance |
|-------|-------------|
| GPT-4 | Excellent - recommended |
| Claude | Very good |
| GPT-3.5 | Acceptable - may need simpler structure |

For weaker models, reduce structural complexity and adjust attribute words.
