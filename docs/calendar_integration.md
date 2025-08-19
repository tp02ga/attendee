# Calendar Integration

Attendee's Calendar integration feature schedules bots to join meetings on your user's calendars. To use this feature you save your users' calendar credentials in Attendee. Attendee uses these credentials to sync calendar events from the Google or Microsoft Calendar APIs. You can then decide which calendar events the bots should join according to your application's business logic.

Many meeting bot based applications build a calendar integration in order to automatically send bots to meetings. Attendee's calendar integration can reduce the amount of time you need to implement this integration, by abstracting away the complexity of interfacing with the Google and Microsoft Calendar APIs.

Below, we'll walk through the steps to implement the calendar integration feature in your application.

## Create a new Google Calendar OAuth Application

You'll need to create a Google OAuth Application that users integrate with so that Attendee can access their calendar events. You can skip this step if your application won't support Google Calendar. We recommend creating separate apps for development and production.

1. Follow the directions [here](https://support.google.com/googleapi/answer/6158849?hl=en) to create a new Google Cloud project that uses OAuth.
2. Enable the Google Calendar API.
3. Use the scopes `['https://www.googleapis.com/auth/calendar.readonly', 'https://www.googleapis.com/auth/userinfo.email']` when creating the OAuth client.
4. Google will need to approve your application before external users can authorize it. See [here](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification) for more information. Until your app is approved, only users that are on an allow-list can authorize it. To edit the allow-list navigate to APIs & Services -> OAuth Consent Screen -> Audience and go to the 'Test Users' section.

## Create a new Microsoft Calendar OAuth Application

You'll need to create a Microsoft Calendar OAuth Application that users integrate with so that Attendee can access their calendar events. You can skip this step if your application won't support Microsoft Calendar. We recommend creating separate apps for development and production.

1. Follow the directions [here](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app) to create a new Microsoft Azure Active Directory application. When it asks you to choose 'Supported account types' select 'Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant) and personal Microsoft accounts (e.g. Skype, Xbox)'.
2. For the API permissions, add these scopes: 'Calendars.Read', 'User.Read'.
3. Microsoft will need to verify your application before external users can authorize it. See [here](https://learn.microsoft.com/en-us/entra/identity-platform/publisher-verification-overview) for more information. This process is entirely automated and should take less than an hour. The steps to get verified are:
    a. [Join the Microsoft AI Cloud Partner Program](https://partner.microsoft.com/en-us/partnership).
    b. [Configure your app's publisher domain](https://learn.microsoft.com/en-us/entra/identity-platform/howto-configure-publisher-domain).
    c. [Mark your app as publisher verified](https://learn.microsoft.com/en-us/entra/identity-platform/mark-app-as-publisher-verified).

## Add calendar webhooks to your Attendee project

If you haven't done so already, we recommend using separate Attendee projects for development and production. These projects will correspond to your development and production OAuth applications.

1. Open your Attendee project and go to Settings -> Webhooks.
2. Click on 'Create Webhook' and select the 'calendar.events_update' and 'calendar.state_change' triggers. The first will be triggered when new calendar events have been updated or created. The second will be triggered if the calendar becomes disconnected.

## Add OAuth flow logic to your application

You'll need to add code to your application to handle the OAuth flow used to let uses authorization your Calendar OAuth Applications. For both Google and Microsoft the flow is essentially the same. 

1. Add an `auth` endpoint that your application will use to redirect users to the OAuth flow.
2. Add a `callback` endpoint that your application will use to handle the OAuth callback.
3. In your callback endpoint, you'll exchange the access code for a refresh token.
4. In your callback endpoint, after you've retrieved the refresh token, make a request to the Attendee API to create a new calendar for the user who just authorized your application. In the request, you'll pass the client id and secret of your application as well as the refresh token. See the API reference for details. You can also pass a deduplication key to prevent duplicate calendars from being created. This could be be the user's email address or internal id.
5. After you make the API request to Attendee, you'll receive a calendar object in the response. Save this calendar object to your database.

## Add Webhook processing logic to your application for the calendar.events_update trigger

When you receive a webhook with trigger type `calendar.events_update`, it means that new calendar events for this user has been synced or updated. The webhook payload itself does not contain the calendar events. Instead after you receive the webhook, you'll need to make a GET request to the Attendee API to retrieve the newly created or updated calendar events. Here are the steps for doing that:

1. Ensure that your database has a column for each calendar to keep track of the last time you've synced it with Attendee.
2. In your GET request to the /calendar_events endpoint, pass the `calendar_id` parameter to filter it to events for that calendar. Also pass the `updated_after` parameter to filter it to events that have been updated since the last time you synced it with Attendee.
3. Paginate through the events returned by the Attendee API.