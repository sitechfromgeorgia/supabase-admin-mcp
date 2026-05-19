# PostgreSQL Functions & Triggers - Common Scenarios & Solutions

## Scenario 1: E-Commerce Order System

### Requirements
- Auto-update product stock on new order
- Calculate order total including discounts
- Prevent overselling
- Log inventory changes

### Implementation

```sql
-- Products table
CREATE TABLE products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  price numeric NOT NULL,
  stock_count int DEFAULT 0,
  updated_at timestamp with time zone DEFAULT now()
);

-- Orders table
CREATE TABLE orders (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  total_amount numeric,
  discount_amount numeric DEFAULT 0,
  status text DEFAULT 'pending',
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Order items
CREATE TABLE order_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id uuid REFERENCES orders(id) ON DELETE CASCADE,
  product_id uuid REFERENCES products(id) ON DELETE RESTRICT,
  quantity int NOT NULL,
  unit_price numeric NOT NULL,
  created_at timestamp with time zone DEFAULT now()
);

-- Inventory logs for audit
CREATE TABLE inventory_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id uuid REFERENCES products(id),
  action text, -- 'order', 'restock', 'adjustment'
  quantity_change int,
  previous_stock int,
  new_stock int,
  created_at timestamp with time zone DEFAULT now()
);

-- Function: Validate stock availability
CREATE OR REPLACE FUNCTION validate_order_stock()
RETURNS TRIGGER AS $$
DECLARE
  v_available_stock int;
BEGIN
  SELECT stock_count INTO v_available_stock
  FROM products WHERE id = NEW.product_id;

  IF v_available_stock < NEW.quantity THEN
    RAISE EXCEPTION 'Insufficient stock for product %. Available: %, Requested: %',
      NEW.product_id, v_available_stock, NEW.quantity;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function: Deduct stock on order
CREATE OR REPLACE FUNCTION deduct_product_stock()
RETURNS TRIGGER AS $$
DECLARE
  v_previous_stock int;
  v_new_stock int;
BEGIN
  -- Get previous stock
  SELECT stock_count INTO v_previous_stock FROM products WHERE id = NEW.product_id;

  -- Deduct stock
  UPDATE products 
  SET stock_count = stock_count - NEW.quantity
  WHERE id = NEW.product_id
  RETURNING stock_count INTO v_new_stock;

  -- Log change
  INSERT INTO inventory_logs (product_id, action, quantity_change, previous_stock, new_stock)
  VALUES (NEW.product_id, 'order', -NEW.quantity, v_previous_stock, v_new_stock);

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Function: Calculate order total
CREATE OR REPLACE FUNCTION calculate_order_total()
RETURNS TRIGGER AS $$
DECLARE
  v_subtotal numeric;
  v_discount numeric;
BEGIN
  -- Calculate subtotal from order items
  SELECT SUM(quantity * unit_price) INTO v_subtotal
  FROM order_items WHERE order_id = NEW.id;

  -- Apply discount (10% for orders > $100)
  v_discount := CASE
    WHEN v_subtotal > 100 THEN v_subtotal * 0.1
    ELSE 0
  END;

  -- Update order
  NEW.total_amount := COALESCE(v_subtotal, 0) - v_discount;
  NEW.discount_amount := v_discount;
  NEW.updated_at := now();

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger: Validate stock before insert
CREATE TRIGGER validate_stock_trigger
BEFORE INSERT ON order_items
FOR EACH ROW
EXECUTE FUNCTION validate_order_stock();

-- Trigger: Deduct stock after insert
CREATE TRIGGER deduct_stock_trigger
AFTER INSERT ON order_items
FOR EACH ROW
EXECUTE FUNCTION deduct_product_stock();

-- Trigger: Calculate total when items added
CREATE TRIGGER calculate_total_trigger
BEFORE INSERT OR UPDATE ON order_items
FOR EACH STATEMENT
EXECUTE FUNCTION calculate_order_total();
```

### TypeScript Usage

```typescript
// Create order with items
const { data: order, error } = await supabase
  .from('orders')
  .insert({ user_id: userId, status: 'pending' })
  .select()
  .single()

if (error) {
  // Catch stock validation errors
  console.error('Error creating order:', error.message)
  return
}

// Add items - triggers will validate and update stock
const { data: items, error: itemsError } = await supabase
  .from('order_items')
  .insert([
    { order_id: order.id, product_id: productId, quantity: 5, unit_price: 29.99 }
  ])
  .select()

// Order total auto-calculated by trigger
const { data: updatedOrder } = await supabase
  .from('orders')
  .select('total_amount, discount_amount')
  .eq('id', order.id)
  .single()

console.log(`Total: $${updatedOrder.total_amount}, Discount: $${updatedOrder.discount_amount}`)
```

---

## Scenario 2: Real-Time Chat Application

### Requirements
- Track user presence (online/offline)
- Auto-create chat thread when messaging
- Count unread messages
- Archive inactive conversations

### Implementation

```sql
-- Users table
CREATE TABLE users (
  id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  username text UNIQUE NOT NULL,
  status text DEFAULT 'offline' CHECK (status IN ('online', 'away', 'offline')),
  last_seen timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Chat threads
CREATE TABLE chat_threads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text,
  is_group boolean DEFAULT false,
  created_by uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamp with time zone DEFAULT now(),
  archived_at timestamp with time zone
);

-- Thread members
CREATE TABLE thread_members (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id uuid REFERENCES chat_threads(id) ON DELETE CASCADE,
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  joined_at timestamp with time zone DEFAULT now(),
  left_at timestamp with time zone,
  UNIQUE(thread_id, user_id)
);

-- Messages
CREATE TABLE messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  thread_id uuid REFERENCES chat_threads(id) ON DELETE CASCADE,
  sender_id uuid REFERENCES users(id) ON DELETE SET NULL,
  content text NOT NULL,
  is_read boolean DEFAULT false,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Message read status
CREATE TABLE message_reads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id uuid REFERENCES messages(id) ON DELETE CASCADE,
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  read_at timestamp with time zone DEFAULT now(),
  UNIQUE(message_id, user_id)
);

-- Function: Update user status
CREATE OR REPLACE FUNCTION update_user_status(p_status text)
RETURNS json
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_result json;
BEGIN
  UPDATE users
  SET status = p_status, last_seen = now(), updated_at = now()
  WHERE id = auth.uid()
  RETURNING row_to_json(users.*) INTO v_result;

  RETURN v_result;
END;
$$;

-- Function: Get unread message count
CREATE OR REPLACE FUNCTION get_unread_count(thread_id uuid)
RETURNS bigint
LANGUAGE sql
SECURITY INVOKER
STABLE
AS $$
  SELECT COUNT(*)
  FROM messages m
  WHERE m.thread_id = $1
    AND m.sender_id != auth.uid()
    AND NOT EXISTS (
      SELECT 1 FROM message_reads mr
      WHERE mr.message_id = m.id AND mr.user_id = auth.uid()
    );
$$;

-- Function: Mark messages as read
CREATE OR REPLACE FUNCTION mark_messages_read(thread_id uuid)
RETURNS int
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_count int;
BEGIN
  -- Get unread messages
  SELECT COUNT(*) INTO v_count FROM messages m
  WHERE m.thread_id = $1
    AND m.sender_id != auth.uid()
    AND NOT EXISTS (
      SELECT 1 FROM message_reads mr
      WHERE mr.message_id = m.id AND mr.user_id = auth.uid()
    );

  -- Mark all as read
  INSERT INTO message_reads (message_id, user_id)
  SELECT m.id, auth.uid()
  FROM messages m
  WHERE m.thread_id = $1
    AND m.sender_id != auth.uid()
    AND NOT EXISTS (
      SELECT 1 FROM message_reads mr
      WHERE mr.message_id = m.id AND mr.user_id = auth.uid()
    )
  ON CONFLICT DO NOTHING;

  RETURN v_count;
END;
$$;

-- Trigger: Auto-create read status on message
CREATE OR REPLACE FUNCTION auto_create_read_status()
RETURNS TRIGGER AS $$
BEGIN
  -- Create read status for all thread members except sender
  INSERT INTO message_reads (message_id, user_id)
  SELECT NEW.id, tm.user_id
  FROM thread_members tm
  WHERE tm.thread_id = NEW.thread_id AND tm.user_id != NEW.sender_id
  ON CONFLICT DO NOTHING;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER message_read_status_trigger
AFTER INSERT ON messages
FOR EACH ROW
EXECUTE FUNCTION auto_create_read_status();

-- Trigger: Auto-archive inactive threads (no messages in 30 days)
CREATE OR REPLACE FUNCTION auto_archive_inactive_threads()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  UPDATE chat_threads
  SET archived_at = now()
  WHERE archived_at IS NULL
    AND id NOT IN (
      SELECT DISTINCT thread_id FROM messages
      WHERE created_at > now() - interval '30 days'
    );
END;
$$;
```

### TypeScript Usage

```typescript
// Update user status
const { data: status } = await supabase.rpc('update_user_status', {
  p_status: 'online'
})

// Get unread count
const { data: unreadCount } = await supabase.rpc('get_unread_count', {
  thread_id: threadId
})

// Mark messages as read
const { data: markedCount } = await supabase.rpc('mark_messages_read', {
  thread_id: threadId
})

// Real-time subscription
supabase
  .channel(`messages:${threadId}`)
  .on('postgres_changes',
    { event: '*', schema: 'public', table: 'messages', filter: `thread_id=eq.${threadId}` },
    (payload) => {
      console.log('New message:', payload.new)
      // Update UI
    }
  )
  .subscribe()
```

---

## Scenario 3: Blog with Comments & Moderation

### Requirements
- Auto-moderate spam comments
- Track comment counts per post
- Notify post author of replies
- Soft-delete with recovery

### Implementation

```sql
-- Comments table
CREATE TABLE comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id uuid REFERENCES posts(id) ON DELETE CASCADE,
  author_id uuid REFERENCES users(id) ON DELETE SET NULL,
  content text NOT NULL,
  status text DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'spam', 'deleted')),
  deleted_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Moderation flags
CREATE TABLE moderation_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  comment_id uuid REFERENCES comments(id) ON DELETE CASCADE,
  action text, -- 'auto_spam', 'user_flag', 'moderator_approval'
  reason text,
  moderator_id uuid REFERENCES users(id),
  created_at timestamp with time zone DEFAULT now()
);

-- Function: Detect spam
CREATE OR REPLACE FUNCTION detect_spam_pattern(content text)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
  -- Simple spam detection (expand as needed)
  RETURN content ILIKE '%viagra%'
    OR content ILIKE '%casino%'
    OR content ILIKE '%click here%'
    OR LENGTH(content) < 5;
END;
$$;

-- Trigger: Auto-moderate spam
CREATE OR REPLACE FUNCTION auto_moderate_comment()
RETURNS TRIGGER AS $$
BEGIN
  IF public.detect_spam_pattern(NEW.content) THEN
    NEW.status := 'spam';
    INSERT INTO moderation_logs (comment_id, action, reason)
    VALUES (NEW.id, 'auto_spam', 'Matched spam pattern');
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER auto_moderate_trigger
BEFORE INSERT ON comments
FOR EACH ROW
EXECUTE FUNCTION auto_moderate_comment();

-- Trigger: Notify on new comment
CREATE OR REPLACE FUNCTION notify_on_comment()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.status = 'approved' THEN
    -- Create notification for post author
    INSERT INTO notifications (user_id, type, related_comment_id, content)
    SELECT 
      p.author_id,
      'comment',
      NEW.id,
      format('New comment on "%s"', p.title)
    FROM posts p
    WHERE p.id = NEW.post_id;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER comment_notification_trigger
AFTER UPDATE ON comments
FOR EACH ROW
WHEN (NEW.status = 'approved' AND OLD.status != 'approved')
EXECUTE FUNCTION notify_on_comment();

-- Function: Get comment count
CREATE OR REPLACE FUNCTION get_comment_count(post_id uuid)
RETURNS bigint
LANGUAGE sql
SECURITY INVOKER
STABLE
AS $$
  SELECT COUNT(*)
  FROM comments
  WHERE post_id = $1 AND status = 'approved' AND deleted_at IS NULL;
$$;

-- Function: Soft-delete comment
CREATE OR REPLACE FUNCTION soft_delete_comment(comment_id uuid, reason text DEFAULT NULL)
RETURNS json
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_result json;
BEGIN
  UPDATE comments
  SET status = 'deleted', deleted_at = now(), updated_at = now()
  WHERE id = comment_id AND author_id = auth.uid()
  RETURNING row_to_json(comments.*) INTO v_result;

  IF v_result IS NULL THEN
    RAISE EXCEPTION 'Comment not found or unauthorized';
  END IF;

  INSERT INTO moderation_logs (comment_id, action, reason)
  VALUES (comment_id, 'user_delete', reason);

  RETURN v_result;
END;
$$;

-- Function: Recover deleted comment
CREATE OR REPLACE FUNCTION recover_comment(comment_id uuid)
RETURNS json
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_result json;
BEGIN
  UPDATE comments
  SET status = 'approved', deleted_at = NULL, updated_at = now()
  WHERE id = comment_id AND author_id = auth.uid() AND deleted_at IS NOT NULL
  RETURNING row_to_json(comments.*) INTO v_result;

  RETURN v_result;
END;
$$;
```

---

## Scenario 4: Subscription Management

### Requirements
- Track subscription status
- Auto-upgrade/downgrade on renewal
- Invoice generation
- Cancellation with refund tracking

### Implementation

```sql
-- Subscription tiers
CREATE TABLE subscription_tiers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text UNIQUE NOT NULL,
  price_monthly numeric NOT NULL,
  features jsonb, -- JSON array of features
  created_at timestamp with time zone DEFAULT now()
);

-- User subscriptions
CREATE TABLE subscriptions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  tier_id uuid REFERENCES subscription_tiers(id),
  status text DEFAULT 'active' CHECK (status IN ('active', 'paused', 'cancelled', 'expired')),
  current_period_start timestamp with time zone,
  current_period_end timestamp with time zone,
  cancelled_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  updated_at timestamp with time zone DEFAULT now()
);

-- Invoices
CREATE TABLE invoices (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  subscription_id uuid REFERENCES subscriptions(id),
  amount numeric NOT NULL,
  status text DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'failed', 'refunded')),
  paid_at timestamp with time zone,
  refunded_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now()
);

-- Function: Create subscription with first invoice
CREATE OR REPLACE FUNCTION create_subscription(tier_id uuid, user_id uuid DEFAULT auth.uid())
RETURNS json
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_sub_id uuid;
  v_price numeric;
  v_result json;
BEGIN
  -- Get tier price
  SELECT price_monthly INTO v_price FROM subscription_tiers WHERE id = $1;

  -- Create subscription
  INSERT INTO subscriptions (user_id, tier_id, current_period_start, current_period_end)
  VALUES (user_id, $1, now(), now() + interval '1 month')
  RETURNING id INTO v_sub_id;

  -- Create initial invoice
  INSERT INTO invoices (subscription_id, amount) VALUES (v_sub_id, v_price);

  -- Return subscription
  SELECT row_to_json(s.*) INTO v_result FROM subscriptions s WHERE id = v_sub_id;
  RETURN v_result;
END;
$$;

-- Trigger: Auto-renew subscription
CREATE OR REPLACE FUNCTION auto_renew_subscription()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  UPDATE subscriptions
  SET
    current_period_start = now(),
    current_period_end = now() + interval '1 month',
    updated_at = now()
  WHERE
    status = 'active'
    AND current_period_end < now()
    AND current_period_end > now() - interval '1 day';

  -- Create invoices for renewed subscriptions
  INSERT INTO invoices (subscription_id, amount)
  SELECT
    s.id,
    st.price_monthly
  FROM subscriptions s
  JOIN subscription_tiers st ON s.tier_id = st.id
  WHERE
    s.status = 'active'
    AND s.current_period_start = now()
    AND NOT EXISTS (
      SELECT 1 FROM invoices i
      WHERE i.subscription_id = s.id
        AND i.created_at > now() - interval '1 hour'
    );
END;
$$;

-- Function: Cancel subscription with refund
CREATE OR REPLACE FUNCTION cancel_subscription(sub_id uuid, refund_reason text DEFAULT NULL)
RETURNS json
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_result json;
BEGIN
  UPDATE subscriptions
  SET status = 'cancelled', cancelled_at = now(), updated_at = now()
  WHERE id = sub_id AND user_id = auth.uid()
  RETURNING row_to_json(subscriptions.*) INTO v_result;

  -- Mark unpaid invoices as refunded
  UPDATE invoices
  SET status = 'refunded', refunded_at = now()
  WHERE subscription_id = sub_id AND status = 'pending';

  RETURN v_result;
END;
$$;
```

---

## Scenario 5: Notification System

### Implementation

```sql
-- Notifications table
CREATE TABLE notifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  type text NOT NULL, -- 'comment', 'like', 'follow', 'message'
  title text NOT NULL,
  content text,
  related_user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  related_item_id uuid,
  is_read boolean DEFAULT false,
  read_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  expires_at timestamp with time zone DEFAULT now() + interval '30 days'
);

-- Function: Mark notification as read
CREATE OR REPLACE FUNCTION mark_notification_read(notif_id uuid)
RETURNS json
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_result json;
BEGIN
  UPDATE notifications
  SET is_read = true, read_at = now()
  WHERE id = notif_id AND user_id = auth.uid()
  RETURNING row_to_json(notifications.*) INTO v_result;

  RETURN v_result;
END;
$$;

-- Function: Mark all as read
CREATE OR REPLACE FUNCTION mark_all_notifications_read()
RETURNS bigint
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_count bigint;
BEGIN
  UPDATE notifications
  SET is_read = true, read_at = now()
  WHERE user_id = auth.uid() AND is_read = false;

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

-- Trigger: Auto-delete expired notifications
CREATE OR REPLACE FUNCTION cleanup_expired_notifications()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  DELETE FROM notifications WHERE expires_at < now();
END;
$$;
```

---

## Scenario 6: Rate Limiting Per IP/User

```sql
-- Rate limit tracker
CREATE TABLE rate_limit_tracker (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES users(id) ON DELETE CASCADE,
  action text NOT NULL,
  request_count int DEFAULT 1,
  window_start timestamp with time zone DEFAULT now(),
  created_at timestamp with time zone DEFAULT now()
);

-- Function: Check rate limit
CREATE OR REPLACE FUNCTION check_rate_limit(action text, limit_per_hour int DEFAULT 60)
RETURNS boolean
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
  v_count int;
BEGIN
  -- Count recent requests
  SELECT COUNT(*) INTO v_count FROM rate_limit_tracker
  WHERE
    user_id = auth.uid()
    AND action = $1
    AND window_start > now() - interval '1 hour';

  IF v_count >= limit_per_hour THEN
    RAISE EXCEPTION 'Rate limit exceeded for action: %', action
      USING ERRCODE = 'RATE_LIMIT_EXCEEDED';
  END IF;

  -- Record this request
  INSERT INTO rate_limit_tracker (user_id, action)
  VALUES (auth.uid(), $1);

  RETURN true;
END;
$$;
```

---

**Last Updated**: January 2025
