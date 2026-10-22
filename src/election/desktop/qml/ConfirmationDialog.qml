import QtQuick
import QtQuick.Controls

Dialog {
    id: dialog
    property string message: ""
    property string acceptLabel: ""
    property string rejectLabel: ""
    property bool confirmationPending: false
    signal confirmed()
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(460, Overlay.overlay.width - 40)
    onAccepted: confirmationPending = true
    onRejected: confirmationPending = false
    onClosed: {
        var accepted = confirmationPending
        confirmationPending = false
        if (accepted) confirmed()
    }
    contentItem: Label { text: dialog.message; textFormat: Text.PlainText; wrapMode: Text.WordWrap }
    footer: DialogButtonBox {
        Button { text: dialog.rejectLabel; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
        Button { text: dialog.acceptLabel; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
    }
}
