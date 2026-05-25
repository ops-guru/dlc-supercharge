# Requirements (Kiro Spec form, EARS-style)

### Requirement 1: Serve feedback form

#### Acceptance Criteria

1. WHEN a GET request is made to `/`, THE Feedback_Collector SHALL return an HTML page containing the Feedback_Form.

### Requirement 2: Validate email server-side

#### Acceptance Criteria

1. WHEN a POST is received at `/feedback`, THE Validator SHALL verify the email field conforms to RFC 5322 server-side.

### Requirement 3: Accessibility

#### Acceptance Criteria

1. THE Feedback_Form SHALL satisfy WCAG 2.1 success criteria including 1.3.1, 2.4.7, 1.4.3.
