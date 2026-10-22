pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var queue
    required property var words
    property string locale: "tc"
    readonly property var editorState: queue.state
    readonly property var form: editorState.forms
    readonly property var context: editorState.context || ({})
    readonly property var latest: editorState.latest_current || ({})
    readonly property var reviewed: editorState.current || ({})
    readonly property bool canEdit: editorState.role === "polling_officer"
        && (context.election || ({})).status === "active"
    readonly property var bands: ["under_30", "30_59", "60_90", "over_90"]
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function bandIndex() { return bands.indexOf(form.band) }
    function languageName(code) {
        return code === "sc" ? "简体中文" : code === "en" ? "English" : "繁體中文"
    }
    function reload() {
        if (!queue.reload(false) && editorState.dirty) discardDialog.open()
    }
    function moveFocus(control, forward) {
        var next = control.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }
    function exportReport(format) {
        if (!editorState.station_id || editorState.busy) return
        pendingFormat = format
        pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/queue-history-"
            + editorState.station_id + "-r" + editorState.revision + "-" + locale + "." + format
        exportDialog.open()
    }

    component Heading: Label {
        textFormat: Text.PlainText
        color: "#25344b"
        font.pixelSize: 20
        font.weight: Font.Medium
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
    component Detail: ColumnLayout {
        id: detail
        required property string caption
        required property string value
        Layout.fillWidth: true
        Layout.alignment: Qt.AlignTop
        spacing: 6
        FormCaption { text: detail.caption }
        Label {
            text: detail.value
            textFormat: Text.PlainText
            color: "#25344b"
            wrapMode: Text.WrapAnywhere
            Layout.fillWidth: true
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("queue"); font.pixelSize: 28 }
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
            onClicked: page.queue.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormNotice {
        words: page.words
        error: page.editorState.error
        notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormNotice {
        words: page.words
        autoReveal: false
        notice: page.editorState.newer_revision ? "queue_newer_revision" : ""
        onReveal: control => page.reveal(control)
    }
    FormCaption {
        visible: !page.editorState.station_id
        text: page.t("select_station")
    }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: latestLayout.implicitHeight + 40
        ColumnLayout {
            id: latestLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 16
            Heading { text: page.t("queue_latest") }
            Label {
                objectName: "queueLiveStatus"
                text: page.t(page.editorState.missing ? "queue_missing"
                    : page.editorState.reminder_due ? "queue_due" : "queue_fresh")
                textFormat: Text.PlainText
                color: page.editorState.missing || page.editorState.reminder_due ? "#975c0e" : "#216a50"
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                Accessible.name: text
            }
            Label {
                visible: !!page.latest.id
                text: page.t("queue_" + (page.latest.band || "under_30"))
                textFormat: Text.PlainText
                font.pixelSize: 26
                font.weight: Font.Medium
                color: "#25344b"
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            GridLayout {
                visible: !!page.latest.id
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 28
                rowSpacing: 20
                Detail { caption: page.t("queue_event_time"); value: page.queue.formatTime(page.latest.event_at || "") }
                Detail { caption: page.t("queue_entered_at"); value: page.queue.formatTime(page.latest.entered_at || "") }
                Detail { caption: page.t("queue_due_at"); value: page.queue.formatTime(page.editorState.due_at || "") }
                Detail { caption: page.t("queue_actor"); value: page.latest.actor_id ? String(page.latest.actor_id) : "—" }
                Detail {
                    objectName: "queueCurrentRevision"
                    caption: page.t("revision")
                    value: String(page.latest.revision || 0)
                }
                Detail { caption: page.t("queue_overdue_periods"); value: String(page.editorState.overdue_periods) }
            }
            FormCaption { text: page.t("last_refresh") + " · " + page.queue.formatTime(page.editorState.server_time || "") }
            FormCaption {
                text: page.t("queue_reviewed") + " · " + page.editorState.revision
                    + (page.reviewed.id ? " · " + page.t("queue_" + page.reviewed.band) : "")
            }
            FormButton {
                objectName: "queueReload"
                text: page.t("reload_saved")
                flat: true
                highlighted: false
                working: page.editorState.busy
                onClicked: page.reload()
                onReveal: control => page.reveal(control)
            }
            FormCaption { visible: !page.canEdit; text: page.t("queue_read_only") }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id && page.canEdit
        implicitHeight: formLayout.implicitHeight + 40
        ColumnLayout {
            id: formLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("queue_form") }
            FormCaption { text: page.t("queue_form_hint") }
            FormCaption { text: page.t("queue_band") }
            ComboBox {
                id: bandPicker
                objectName: "queueBand"
                Layout.fillWidth: true
                model: page.bands
                currentIndex: page.bandIndex()
                displayText: page.t("queue_" + page.form.band)
                enabled: !page.editorState.busy
                Accessible.name: page.t("queue_band")
                delegate: ItemDelegate {
                    required property string modelData
                    required property int index
                    width: bandPicker.width
                    text: page.t("queue_" + modelData)
                    highlighted: bandPicker.highlightedIndex === index
                }
                onActivated: page.queue.setField("band", page.bands[currentIndex])
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (bandPicker.activeFocus) page.reveal(bandPicker) })
            }
            FormCaption { text: page.t("queue_event_time") }
            FormField {
                objectName: "queueEventTime"
                text: page.form.event_time
                placeholderText: "YYYY-MM-DD HH:mm"
                working: page.editorState.busy
                Accessible.name: page.t("queue_event_time")
                onTextEdited: page.queue.setField("event_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("queue_reason") }
            TextArea {
                id: reasonField
                objectName: "queueReason"
                Layout.fillWidth: true
                implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
                text: page.form.reason
                textFormat: TextEdit.PlainText
                wrapMode: TextEdit.WordWrap
                clip: true
                selectByMouse: true
                enabled: !page.editorState.busy
                padding: 12
                Accessible.name: page.t("queue_reason")
                Keys.priority: Keys.BeforeItem
                Keys.onTabPressed: event => { page.moveFocus(reasonField, true); event.accepted = true }
                Keys.onBacktabPressed: event => { page.moveFocus(reasonField, false); event.accepted = true }
                onTextEdited: page.queue.setField("reason", text)
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (reasonField.activeFocus) page.reveal(reasonField) })
                background: Rectangle {
                    radius: 8
                    color: "white"
                    border.color: reasonField.activeFocus ? "#1967d2" : "#a7b2c2"
                    border.width: reasonField.activeFocus ? 2 : 1
                }
            }
            FormCaption { text: page.t("queue_confirm_hint") }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 780 ? 2 : 1
                columnSpacing: 12
                rowSpacing: 8
                FormButton {
                    objectName: "queueSave"
                    text: page.t(page.editorState.busy ? "saving" : "queue_save")
                    Layout.fillWidth: true
                    working: page.editorState.busy
                    onClicked: page.queue.save()
                    onReveal: control => page.reveal(control)
                }
                FormButton {
                    objectName: "queueConfirmUnchanged"
                    text: page.t("queue_confirm")
                    Layout.fillWidth: true
                    working: page.editorState.busy
                    enabled: !working && !!page.reviewed.id
                    flat: true
                    highlighted: false
                    onClicked: page.queue.confirmUnchanged()
                    onReveal: control => page.reveal(control)
                }
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 20
            Heading { text: page.t("queue_history") }
            FormCaption { visible: page.editorState.items.length === 0; text: page.t("queue_no_history") }
            Repeater {
                model: page.editorState.items
                delegate: ColumnLayout {
                    id: historyEntry
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 6
                    Label {
                        text: page.t("revision") + " " + historyEntry.modelData.revision
                            + " · " + page.t("queue_" + historyEntry.modelData.kind)
                            + " · " + page.t("queue_" + historyEntry.modelData.band)
                            + (page.latest.id === historyEntry.modelData.id ? " · " + page.t("queue_current_marker") : "")
                        textFormat: Text.PlainText
                        color: "#25344b"
                        font.weight: Font.Medium
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    FormCaption { text: page.t("queue_event_time") + " · " + page.queue.formatTime(historyEntry.modelData.event_at) }
                    FormCaption { text: page.t("queue_entered_at") + " · " + page.queue.formatTime(historyEntry.modelData.entered_at) }
                    FormCaption { text: page.t("queue_actor") + " · " + historyEntry.modelData.actor_id }
                    FormCaption {
                        visible: !!historyEntry.modelData.confirmed_event_id
                        text: page.t("queue_confirms") + " · " + (historyEntry.modelData.confirmed_event_id || "—")
                    }
                    FormCaption { visible: !!historyEntry.modelData.reason; text: historyEntry.modelData.reason }
                    Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: "#e1e7f0" }
                }
            }
        }
    }

    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: reportLayout.implicitHeight + 40
        ColumnLayout {
            id: reportLayout
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12
            Heading { text: page.t("queue_report") }
            FormCaption { text: page.t("queue_report_hint") }
            FormCaption { text: page.t("stock_report_language") + " · " + page.languageName(page.locale) + " · " + page.t("revision") + " " + page.editorState.revision }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 900 ? 3 : 1
                columnSpacing: 12
                rowSpacing: 8
                FormButton {
                    objectName: "queuePreview"
                    text: page.t("stock_preview")
                    working: page.editorState.busy
                    Layout.fillWidth: true
                    onClicked: page.queue.preview(page.locale)
                    onReveal: control => page.reveal(control)
                }
                FormButton {
                    objectName: "queueExportPdf"
                    text: page.t("stock_export_pdf")
                    working: page.editorState.busy
                    Layout.fillWidth: true
                    flat: true
                    highlighted: false
                    onClicked: page.exportReport("pdf")
                    onReveal: control => page.reveal(control)
                }
                FormButton {
                    objectName: "queueExportCsv"
                    text: page.t("stock_export_csv")
                    working: page.editorState.busy
                    Layout.fillWidth: true
                    flat: true
                    highlighted: false
                    onClicked: page.exportReport("csv")
                    onReveal: control => page.reveal(control)
                }
            }
            FormCaption {
                visible: !!page.editorState.report_text
                text: page.t("stock_preview_language") + " · " + page.languageName((page.editorState.report || ({})).locale || page.locale)
            }
            TextArea {
                id: reportText
                objectName: "queueReportPreview"
                visible: !!page.editorState.report_text
                Layout.fillWidth: true
                readOnly: true
                selectByMouse: true
                text: page.editorState.report_text || ""
                textFormat: TextEdit.PlainText
                wrapMode: TextEdit.WrapAnywhere
                clip: true
                Accessible.name: page.t("queue_report")
                Keys.priority: Keys.BeforeItem
                Keys.onTabPressed: event => { page.moveFocus(reportText, true); event.accepted = true }
                Keys.onBacktabPressed: event => { page.moveFocus(reportText, false); event.accepted = true }
                onActiveFocusChanged: if (activeFocus)
                    Qt.callLater(function() { if (reportText.activeFocus) page.reveal(reportText) })
            }
            FormCaption {
                visible: !!page.editorState.export_path
                text: page.t("stock_export_location") + "\n" + (page.editorState.export_path || "")
            }
        }
    }
    ConfirmationDialog {
        id: discardDialog
        title: page.t("discard_changes")
        message: page.t("unsaved_queue_changes")
        acceptLabel: page.t("discard_changes")
        rejectLabel: page.t("keep_editing")
        onConfirmed: page.queue.reload(true)
    }
    FileDialog {
        id: exportDialog
        title: page.t(page.pendingFormat === "pdf" ? "stock_export_pdf" : "stock_export_csv")
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.queue.download(page.pendingFormat, selectedFile.toString(), page.pendingLocale)
    }
}
