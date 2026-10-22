import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: noticeBox
    required property var words
    property string error: ""
    property string notice: ""
    signal reveal(var control)
    visible: !!error || !!notice
    Layout.fillWidth: true
    implicitHeight: message.implicitHeight + 28
    radius: 10
    color: error ? "#fceceb" : "#e8f5ef"
    function revealFeedback() {
        Qt.callLater(function() {
            if ((!noticeBox.error && !noticeBox.notice) || !noticeBox.visible) return
            noticeBox.forceActiveFocus(Qt.OtherFocusReason)
            noticeBox.reveal(noticeBox)
        })
    }
    onErrorChanged: if (error) revealFeedback()
    onNoticeChanged: if (notice && !error) revealFeedback()
    Label {
        id: message
        anchors.fill: parent
        anchors.margins: 14
        text: noticeBox.words[noticeBox.error || noticeBox.notice] || noticeBox.error || noticeBox.notice
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        color: noticeBox.error ? "#a52c27" : "#216a50"
        Accessible.role: Accessible.StaticText
        Accessible.name: text
    }
}
