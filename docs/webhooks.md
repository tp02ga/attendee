# Webhooks

Attendee provides a webhook system that allows you to receive real-time notifications about important events in your Attendee bots and meetings.

## Overview

Webhooks allow your application to receive notifications when events occur in Attendee. Instead of constantly polling Attendee's API for updates, webhooks deliver information to your application in real-time as events occur.

## Key Benefits

- **Real-time updates**: Get notified immediately when an event occurs
- **Reduced API calls**: No need to poll for status changes
- **Automation**: Trigger workflows based on Attendee events

## Creating a Webhook

To create a webhook:

1. Navigate to your project and click on the "Webhooks" section in the sidebar
2. Click "Create Webhook" 
3. Provide an HTTPS URL that will receive webhook events
4. Select the events you want to receive notifications for (we currently have one event type: `bot.state_change`)
5. Click "Create" to save your subscription

## Webhook Payloads

When a webhook is delivered, Attendee will send an HTTP POST request to your webhook URL with the following structure:

```json
{
  "idempotency_key": { /* UUID that uniquely identifies this webhook delivery */ },
  "bot_id": { /* Id of the bot associated with the webhook delivery */ },
  "bot_metadata": { /* Any metadata associated with the bot */ },
  "trigger": {/* Trigger for the webhook. Currently, the only trigger is bot.state_change, which is fired whenever the bot changes its state. */},
  "data": { /* Event-specific data */ }
}
```

### Payload for `bot.state_change` trigger

For webhooks triggered by `bot.state_change`, the `data` field contains:


```json
{
  "new_state": { /* The current state of the bot */ },
  "old_state": { /* The previous state of the bot */ },
  "created_at": { /* The timestamp when the state change occurred */ },
  "event_type": { /* The type of event that triggered the state change */ },
  "event_sub_type": { /* The sub-type of event that triggered the state change */ },
}
```

### Using webhooks to know when the recording is available

The most common use case for webhooks is to know when the meeting has ended and the recording is available. You can do this by listening for the `post_processing_completed` event type.

The data field will look like this

```json
{
  "new_state": "ended",
  "old_state": "post_processing",
  "created_at": "2023-07-15T14:30:45.123456Z",
  "event_type": "post_processing_completed",
  "event_sub_type": null,
}
```

## Verifying Webhooks

To ensure the webhook requests are coming from Attendee, we sign each request with a secret key. You can verify this signature to confirm the authenticity of the request.

The signature is included in the `X-Webhook-Signature` header of each webhook request.

## Webhook Retry Policy

If your endpoint returns a non-2xx status code or fails to respond within 10 seconds, Attendee will retry the webhook delivery up to 3 times with exponential backoff.
