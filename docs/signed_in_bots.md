# Signed In Bots

Signed in bots login to a user account for the meeting platform before joining the meeting. By default, bots are not associated with a specific user account, they're doing the equivalent of opening an incognito window and navigating to the meeting URL.

## Why Use Signed In Bots?

There are several advantages to using a signed-in bot:

*   **Appearance**: Signed-in bots appear as a normal user rather than an anonymous one, so they have an avatar and don't have the 'Unverified' labels that some meeting platforms add for anonymous users. 
*   **Access**: Some meetings are configured to not allow anonymous users to join at all. In these cases, a signed-in bot is required to join the meeting.

The downsides of signed in bots are that it will take slightly longer to join the meeting and there is some setup work required.

## Signed in Teams Bots

We currently support signed-in bots for Microsoft Teams. Here's how to set it up:

1.  Create a new Microsoft business account for the bot to use. It is important to disable two-factor authentication (2FA) on this account so that the bot can log in with only an email and password. If you encounter any issues with this step, please reach out to us on Slack.
2.  Navigate to the Settings -> Credentials page, scroll down to Teams Bot Login Credentials and add the email and password for the account you created.
3.  When calling the create bot endpoint, you must pass the following parameter to instruct the bot to use the stored credentials to sign in before joining: `"teams_settings": {"use_login": true}`.

## Sign in Bots for Other Platforms

Currently, we do not support signed-in bots for platforms other than Microsoft Teams.
