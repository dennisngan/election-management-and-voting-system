pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var workspace
    required property var words
    readonly property var editorState: workspace.state
    readonly property var selected: editorState.selected
    readonly property var election: selected.election || ({})
    readonly property var constituency: selected.constituency || ({})
    readonly property var station: selected.station || ({})
    readonly property var account: selected.account || ({})
    readonly property bool hasSelected: !!station.id
    property int pendingStationId: 0
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function contextLabel(context) {
        return context.election.name + " · " + context.constituency.code + " · "
            + context.constituency.name + " · " + context.station.code + " · " + context.station.name
    }
    function selectedIndex() {
        for (var i = 0; i < editorState.contexts.length; i++)
            if (editorState.contexts[i].station.id === station.id) return i
        return -1
    }
    function restoreStationPicker() {
        stationPicker.currentIndex = Qt.binding(function() { return page.selectedIndex() })
    }
    function chooseStation(stationId) {
        if (editorState.busy || stationId === station.id) return
        if (workspace.selectionGuarded) {
            pendingStationId = stationId
            discardDialog.open()
        } else workspace.selectStation(stationId)
        restoreStationPicker()
    }

    Connections {
        target: page.workspace
        function onStateChanged() {
            Qt.callLater(function() { page.restoreStationPicker() })
        }
    }

    component ContextDetail: ColumnLayout {
        required property string caption
        required property string value
        id: detail
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        spacing: 6
        FormCaption { text: detail.caption }
        Label {
            text: detail.value
            textFormat: Text.PlainText
            color: "#25344b"
            font.pixelSize: 16
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Label {
            text: page.t("station_context")
            textFormat: Text.PlainText
            color: "#25344b"
            font.pixelSize: 28
            font.weight: Font.Medium
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running
            implicitWidth: 28
            implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            text: page.t("refresh")
            flat: true
            highlighted: false
            working: page.editorState.busy || page.editorState.refreshing
            onClicked: page.workspace.refresh()
            onReveal: control => page.reveal(control)
        }
    }

    FormNotice {
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }

    FormPanel {
        implicitHeight: selectionLayout.implicitHeight + 40
        ColumnLayout {
            id: selectionLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            FormCaption { text: page.t("select_station") }
            ComboBox {
                id: stationPicker
                objectName: "workspaceStationPicker"
                Layout.fillWidth: true
                visible: page.editorState.contexts.length > 0
                enabled: !page.editorState.busy
                model: page.editorState.contexts
                currentIndex: page.selectedIndex()
                displayText: currentIndex >= 0
                    ? page.contextLabel(model[currentIndex]) : page.t("select_station")
                Accessible.name: page.t("select_station")
                contentItem: Text {
                    text: stationPicker.displayText
                    textFormat: Text.PlainText
                    font: stationPicker.font
                    color: "#25344b"
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                }
                delegate: ItemDelegate {
                    id: stationDelegate
                    required property var modelData
                    required property int index
                    width: stationPicker.width
                    text: page.contextLabel(modelData)
                    highlighted: stationPicker.highlightedIndex === index
                    contentItem: Text {
                        text: stationDelegate.text
                        textFormat: Text.PlainText
                        color: "#25344b"
                        font: stationDelegate.font
                        wrapMode: Text.WordWrap
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                onActivated: {
                    page.chooseStation(model[currentIndex].station.id)
                    // The server's accepted context controls selection, including after a denial.
                    page.restoreStationPicker()
                }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { page.reveal(stationPicker) })
            }
            FormCaption {
                visible: page.editorState.contexts.length === 0
                text: page.t(page.editorState.busy || page.editorState.refreshing
                    ? "loading" : "no_assigned_stations")
            }
            FormCaption {
                visible: page.editorState.contexts.length > 0 && !page.hasSelected
                text: page.t("select_station")
            }
        }
    }

    FormPanel {
        visible: page.hasSelected
        implicitHeight: contextLayout.implicitHeight + 40
        ColumnLayout {
            id: contextLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 20
            RowLayout {
                Layout.fillWidth: true
                Label {
                    text: page.station.code && page.station.name
                        ? page.station.code + " · " + page.station.name : ""
                    textFormat: Text.PlainText
                    color: "#25344b"
                    font.pixelSize: 22
                    font.weight: Font.Medium
                    wrapMode: Text.WrapAnywhere
                    Layout.fillWidth: true
                }
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 28
                rowSpacing: 24
                ContextDetail {
                    caption: page.t("selected_election")
                    value: page.election.name || ""
                }
                ContextDetail {
                    caption: page.t("election_status")
                    value: page.election.status ? page.t(page.election.status) : ""
                }
                ContextDetail {
                    caption: page.t("constituency_name")
                    value: page.constituency.code && page.constituency.name
                        ? page.constituency.code + " · " + page.constituency.name : ""
                }
                ContextDetail {
                    caption: page.t("counting_mode")
                    value: page.station.counting_mode
                        ? page.t(page.station.counting_mode === "send"
                            ? "send_to_destination" : "local_counting") : ""
                }
                ContextDetail {
                    caption: page.t("account")
                    value: page.account.display_name && page.account.username
                        ? page.account.display_name + "\n" + page.account.username : ""
                }
                ContextDetail {
                    caption: page.t("role")
                    value: page.account.role ? page.t(page.account.role) : ""
                }
            }
        }
    }

    ConfirmationDialog {
        id: discardDialog
        title: page.t("discard_changes")
        message: page.t("unsaved_station_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: {
            page.workspace.selectStation(page.pendingStationId, true)
            page.restoreStationPicker()
        }
    }
}
