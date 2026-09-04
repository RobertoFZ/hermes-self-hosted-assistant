# Collected PR 88 evidence

GitHub metadata reports 32 additions, 18 deletions, and 4 changed files. Discussion history is complete. No database, OpenSpec, gitlink, or stack relationship exists.

```diff
diff --git a/app/services/legacy_retry_policy.rb b/app/services/legacy_retry_policy.rb
deleted file mode 100644
--- a/app/services/legacy_retry_policy.rb
+++ /dev/null
@@ -1,8 +0,0 @@
-class LegacyRetryPolicy
-  MAX_ATTEMPTS = 3
-
-  def retry?(attempt)
-    attempt.transient_failure? && attempt.count < MAX_ATTEMPTS
-  end
-end
-
diff --git a/app/models/payment_attempt.rb b/app/models/payment_attempt.rb
--- a/app/models/payment_attempt.rb
+++ b/app/models/payment_attempt.rb
@@ -1,10 +1,10 @@
-class PaymentAttempt
-  def retryable?
-    LegacyRetryPolicy.new.retry?(self)
-  end
-
-  def retry!
-    update!(status: "queued")
-  end
-end
-
+class PaymentAttempt
+  def retryable?
+    transient_failure? && retry_count < 3
+  end
+
+  def mark_retrying!
+    update!(status: "retrying")
+  end
+end
+
diff --git a/app/services/retry_charge.rb b/app/services/retry_charge.rb
new file mode 100644
--- /dev/null
+++ b/app/services/retry_charge.rb
@@ -0,0 +1,22 @@
+class RetryCharge
+  def initialize(attempt)
+    @attempt = attempt
+  end
+
+  def call
+    return :not_retryable unless attempt.retryable?
+
+    attempt.mark_retrying!
+    enqueue
+    :queued
+  end
+
+  private
+
+  attr_reader :attempt
+
+  def enqueue
+    RetryChargeJob.perform_later(attempt.id)
+  end
+end
+
```
