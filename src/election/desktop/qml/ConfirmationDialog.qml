import QtQuick
import QtQuick.Controls

Dialog {
    id: dialog
    property string message: ""
    property string acceptLabel: ""
    property string rejectLabel: ""
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(460, Overlay.overlay.width - 40)
    contentItem: Label { text: dialog.message; textFormat: Text.PlainText; wrapMode: Text.WordWrap }
    footer: DialogButtonBox {
        Button { text: dialog.rejectLabel; DialogButtonBox.buttonRole: DialogButtonBox.RejectRole }
        Button { text: dialog.acceptLabel; DialogButtonBox.buttonRole: DialogButtonBox.AcceptRole }
    }
}
