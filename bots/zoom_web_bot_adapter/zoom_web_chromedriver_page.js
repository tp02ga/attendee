const client = ZoomMtgEmbedded.createClient()

let meetingSDKElement = document.getElementById('meetingSDKElement')

var authEndpoint = ''
var sdkKey = ''
var meetingNumber = 84315220467
var passWord = ''
var role = 0
var userName = 'Zoom Web Bot'
var userEmail = ''
var registrantToken = ''
var zakToken = ''

function joinMeeting() {
    const signature = '';
    startMeeting(signature);
}

function startMeeting(signature) {

  client.init({zoomAppRoot: meetingSDKElement, language: 'en-US', patchJsMedia: true, leaveOnPageUnload: true}).then(() => {
    client.join({
      signature: signature,
      sdkKey: sdkKey,
      meetingNumber: meetingNumber,
      password: passWord,
      userName: userName,
      userEmail: userEmail,
      tk: registrantToken,
      zak: zakToken
    }).then(() => {
      console.log('joined successfully')
    }).catch((error) => {
      console.log(error)
    })
  }).catch((error) => {
    console.log(error)
  })
}