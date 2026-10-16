# RAG Evaluation

## Overview

This document describes the quality dimensions used to evaluate the Retrieval-Augmented Generation (RAG) component of the Agentic RAG system.

The objective is to verify that answers are accurate, grounded in the knowledge base, relevant to the user's question, and appropriately withheld when supporting evidence is unavailable.

## 1. Correctness

**Purpose:** Evaluate whether the generated answer matches the expected answer.

Correctness is assessed by comparing system responses against expected answers in the RAG evaluation dataset.

**Example:**
- Question: How many days of annual leave are provided?
- Expected answer: 20 days.
- System answer: 20 days.
- Result: Correct.

## 2. Faithfulness (Groundedness)

**Purpose:** Evaluate whether claims in the generated answer are supported by the retrieved document context.

A response can sound plausible but still be unfaithful if it includes information that the retrieved evidence does not support.

**Example:**
- Retrieved context: Annual leave entitlement is 20 days.
- System answer: Employees receive 30 days of annual leave.
- Result: Unfaithful to the retrieved context.

Faithfulness should be evaluated against the actual retrieved evidence, not just whether the answer sounds reasonable.

## 3. Context Relevance

**Purpose:** Evaluate whether the retrieved document chunks are relevant to the user's question.

Relevant context gives the generation step useful evidence to answer the question.

**Example:**
- Question: What are the hospital visiting hours?
- Retrieved context: Hospital visiting hours from the hospital information document.
- Result: Relevant context.

## 4. Answer Relevance

**Purpose:** Evaluate whether the generated response directly addresses the user's question.

A factually correct response can still be irrelevant if it answers a different question.

## 5. No-Answer Behavior

**Purpose:** Verify that the system does not invent an answer when the knowledge base does not contain sufficient supporting information.

The system should return its configured fallback:

`I don't know based on the provided documents.`

When the answer is unknown, the response should not present unsupported claims or misleading document sources.

## Evaluation Approach

Use a fixed set of questions with expected answers and supporting documents. Include answerable questions, questions with insufficient evidence, and questions that test retrieval quality.

Record the following for each test:
- User question
- Expected answer
- Generated answer
- Retrieved context and source
- Correctness result
- Faithfulness result
- Relevance result
- No-answer behavior, where applicable

## Current Status

The project includes RAG evaluation datasets and tests.

The existence of these tests does not by itself establish a measured faithfulness or correctness score. Quantitative results should be reported only after the relevant metrics have been evaluated and the results recorded.

## Conclusion

RAG evaluation helps identify retrieval failures, unsupported answers, irrelevant responses, and incorrect fallback behavior. These checks complement the system's retrieval thresholds, document citations, and no-answer fallback.