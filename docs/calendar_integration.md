# Calendar Integration

Attendee's Calendar integration feature schedules bots to join meetings on your user's calendars. To use this feature you save your users' calendar credentials in Attendee. Attendee uses these credentials to sync calendar events from the Google or Microsoft Calendar APIs. You can then decide which calendar events the bots should join according to your application's business logic.

Many meeting bot based applications build a calendar integration in order to automatically send bots to meetings. Attendee's calendar integration can reduce the amount of time you need to implement this integration, by abstracting away the complexity of interfacing with the Google and Microsoft Calendar APIs.

Below, we'll walk through the steps to implement the calendar integration feature in your application.

## 1. Create a new Google Calendar API project

You'll need to create a Google OAuth Application that users integrate with so that you can access their calendar events.

1. Follow the directions [here](https://support.google.com/googleapi/answer/6158849?hl=en) to create a new Google Cloud project that uses OAuth.
2. Enable the Google Calendar API.
3. Use the scopes `['https://www.googleapis.com/auth/calendar.readonly', 'https://www.googleapis.com/auth/userinfo.email']` when creating the OAuth client.
4. Copy the client ID and client secret.

## 2. Create a new Microsoft Graph API project

You'll need to create a Microsoft Graph API project that users integrate with so that you can access their calendar events.

1. Create a new Microsoft Azure Active Directory application.