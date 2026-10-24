pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtCore
import QtQuick.Layouts

ColumnLayout {
    id: page
    required property var papers
    required property var words
    property string locale: "tc"
    readonly property var editorState: papers.state
    readonly property var form: editorState.forms || ({})
    readonly property var selected: editorState.selected || ({})
    readonly property var basis: editorState.basis || ({})
    readonly property var election: (editorState.context || ({})).election || ({})
    readonly property bool canCreate: !!editorState.station_id
        && editorState.role === "polling_officer"
        && (election.status === "draft" || election.status === "active")
    readonly property bool canEdit: canCreate && !editorState.historical
        && (!selected.id || editorState.editing)
    readonly property bool working: editorState.busy || editorState.refreshing
    property int seriesIndex: 0
    readonly property var series: editorState.series_reports[seriesIndex] || ({})
    readonly property var quantityKeys: ["received_quantity", "ordinary_issued_quantity",
        "replacement_issued_quantity", "spoilt_original_quantity", "tendered_issued_quantity",
        "retrieved_refused_quantity", "retrieved_found_quantity", "retrieved_held_quantity",
        "retrieved_unused_quantity", "ordinary_unissued_quantity", "replacement_unissued_quantity",
        "tendered_unissued_quantity", "never_issued_quantity", "estimated_box_papers_quantity"]
    property string pendingAction: "new"
    property int pendingId: 0
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function requestRecord(action, recordId) {
        if (working) return
        if (editorState.dirty) {
            pendingAction = action; pendingId = recordId; discardDialog.open()
        } else switchRecord(action, recordId, false)
    }
    function switchRecord(action, recordId, discard) {
        if (action === "new") return papers.newSnapshot(discard)
        if (action === "revision") return papers.loadRevision(recordId, discard)
        return papers.loadSnapshot(recordId, discard)
    }
    function summaryName(key) {
        if (key === "never_issued_quantity") return "specialNeverIssuedTotal"
        if (key === "retrieved_unused_quantity") return "specialRetrievedTotal"
        if (key === "estimated_box_papers_quantity") return "specialEstimatedBoxTotal"
        return "specialTotal_" + key
    }
    function exportReport(format) {
        if (!selected.id || working) return
        pendingFormat = format; pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        exportDialog.selectedFile = exportDialog.currentFolder.toString() + "/special-papers-"
            + selected.id + "-r" + selected.revision + "-" + pendingLocale + "." + format
        exportDialog.open()
    }
    component Heading: Label {
        Layout.fillWidth: true
        color: "#25344b"; font.pixelSize: 20; font.weight: Font.Medium
        textFormat: Text.PlainText; wrapMode: Text.WordWrap
    }
    component Action: FormButton {
        id: action
        Layout.fillWidth: true
        implicitHeight: Math.max(48, contentItem.implicitHeight + 24)
        contentItem: Text {
            text: action.text; font: action.font
            color: !action.enabled ? "#8a96a8" : action.highlighted ? "white" : "#1967d2"
            textFormat: Text.PlainText; wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
        }
        onReveal: control => page.reveal(control)
    }
    component MultilineField: TextArea {
        id: field
        Layout.fillWidth: true
        selectByMouse: true; textFormat: TextEdit.PlainText; wrapMode: TextEdit.WrapAnywhere
        topPadding: 12; bottomPadding: 12; leftPadding: 12; rightPadding: 12
        topInset: 0; bottomInset: 0; leftInset: 0; rightInset: 0
        implicitHeight: Math.max(96, contentHeight + topPadding + bottomPadding)
        background: Rectangle { color: "white"; radius: 8; border.color: "#c4cedc" }
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => {
            let next = field.nextItemInFocusChain(true)
            if (next) next.forceActiveFocus(Qt.TabFocusReason)
            event.accepted = true
        }
        Keys.onBacktabPressed: event => {
            let next = field.nextItemInFocusChain(false)
            if (next) next.forceActiveFocus(Qt.BacktabFocusReason)
            event.accepted = true
        }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (field.activeFocus) page.reveal(field)
        })
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { text: page.t("special_title"); font.pixelSize: 28 }
        BusyIndicator { running: page.working; visible: running }
        FormButton {
            objectName: "specialRefresh"
            text: page.t("refresh"); highlighted: false; working: page.working
            onClicked: page.papers.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormNotice {
        words: page.words; error: page.editorState.error; notice: page.editorState.notice
        onReveal: control => page.reveal(control)
    }
    FormCaption { text: page.t("special_intro") }
    FormCaption {
        objectName: "specialBasisStale"
        visible: page.editorState.latest_basis_current === false
        text: page.t("special_basis_stale"); color: "#9a5b00"
    }
    FormNotice {
        words: page.words; autoReveal: false
        notice: page.editorState.newer_revision ? "special_paper_newer_revision" : ""
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: recordsLayout.implicitHeight + 40
        ColumnLayout {
            id: recordsLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("special_records") }
            FormCaption { visible: page.editorState.items.length === 0; text: page.t("special_empty") }
            ComboBox {
                id: recordPicker
                objectName: "specialPicker"
                Layout.fillWidth: true; enabled: !page.working
                model: page.editorState.items
                currentIndex: model.findIndex(row => row.id === page.selected.id)
                displayText: page.selected.id ? page.t("special_observation") + " "
                    + page.selected.id + " · " + page.t("revision") + " " + page.selected.revision
                    : page.t("special_select")
                Accessible.name: page.t("special_select")
                delegate: ItemDelegate {
                    required property var modelData
                    width: recordPicker.width
                    text: modelData.id + " · " + page.papers.formatTime(modelData.event_at)
                        + " · " + page.t("revision") + " " + modelData.revision
                }
                onActivated: page.requestRecord("record", model[currentIndex].id)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (recordPicker.activeFocus) page.reveal(recordPicker)
                })
            }
            FormCaption {
                objectName: "specialEventContext"; visible: !!page.selected.id
                text: page.papers.formatTime(page.selected.event_at || "") + "\n"
                    + page.t("server_entry") + " · "
                    + page.papers.formatTime(page.selected.entered_at || "") + "\n"
                    + page.t("entered_by") + " · " + (page.selected.actor_id || "—")
            }
            FormCaption { visible: !!page.selected.reason; text: page.selected.reason || "" }
            FormCaption { visible: page.editorState.historical; text: page.t("special_historical") }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 740 ? 3 : 1
                Action {
                    objectName: "specialNew"; visible: page.canCreate
                    text: page.t("special_new"); working: page.working
                    onClicked: page.requestRecord("new", 0)
                }
                Action {
                    objectName: "specialEdit"
                    visible: page.canCreate && !!page.selected.id && !page.editorState.historical
                        && !page.editorState.editing && page.editorState.history_verified
                    text: page.t("special_edit"); working: page.working
                    onClicked: page.papers.editSelected()
                }
                Action {
                    objectName: "specialReload"; visible: !!page.selected.id
                    text: page.t("reload_saved"); highlighted: false; working: page.working
                    onClicked: page.requestRecord("record", page.selected.id)
                }
            }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: formLayout.implicitHeight + 40
        ColumnLayout {
            id: formLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("special_observation") }
            FormCaption { text: page.t("special_event_time") }
            FormField {
                objectName: "specialEventTime"
                text: page.form.event_time || ""; readOnly: !page.canEdit; working: page.working
                Accessible.name: page.t("special_event_time")
                onTextEdited: page.papers.setField("event_time", text)
                onReveal: control => page.reveal(control)
            }
            FormCaption { text: page.t("special_basis_hint") }
            ComboBox {
                id: basisPicker
                objectName: "specialBasisPicker"
                Layout.fillWidth: true; enabled: page.canEdit && !page.working
                model: [{id: 0, revision: 0}].concat(page.editorState.basis_options)
                currentIndex: Math.max(0, model.findIndex(row => row.id === page.basis.id
                    && row.revision === page.basis.revision))
                displayText: page.basis.id ? "P(12) " + page.basis.id + " · "
                    + page.t("revision") + " " + page.basis.revision + " · "
                    + page.papers.formatTime(page.basis.event_at || "") : page.t("special_choose_basis")
                Accessible.name: page.t("special_basis")
                delegate: ItemDelegate {
                    required property var modelData
                    width: basisPicker.width
                    text: modelData.id ? "P(12) " + modelData.id + " · " + page.t("revision")
                        + " " + modelData.revision + " · " + page.papers.formatTime(modelData.event_at)
                        : page.t("special_choose_basis")
                }
                onActivated: if (currentIndex > 0) page.papers.selectBasis(model[currentIndex].id)
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (basisPicker.activeFocus) page.reveal(basisPicker)
                })
            }
            FormCaption { text: page.t("special_count_hint") }
            Action {
                objectName: "specialZeroAll"; visible: page.canEdit
                text: page.t("special_zero_all"); highlighted: false; working: page.working
                onClicked: page.papers.zeroAll()
            }
            FormCaption { text: page.t("special_series") }
            ComboBox {
                id: seriesPicker
                objectName: "specialSeriesPicker"
                Layout.fillWidth: true; enabled: !page.working && model.length > 0
                model: page.editorState.series_reports.map(row => row.series)
                currentIndex: Math.min(page.seriesIndex, model.length - 1)
                onActivated: page.seriesIndex = currentIndex
                Accessible.name: page.t("special_series")
                onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
                    if (seriesPicker.activeFocus) page.reveal(seriesPicker)
                })
            }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 740 ? 2 : 1
                visible: !!page.series.series
                Repeater {
                    model: ["replacement_issued_quantity", "spoilt_original_quantity",
                        "tendered_issued_quantity", "retrieved_refused_quantity",
                        "retrieved_found_quantity", "retrieved_held_quantity"]
                    delegate: ColumnLayout {
                        required property string modelData
                        Layout.fillWidth: true
                        FormCaption { text: page.t("special_" + parent.modelData) }
                        FormField {
                            id: countField
                            objectName: "specialCount_" + parent.modelData
                            text: page.series[parent.modelData] || ""
                            readOnly: !page.canEdit; working: page.working
                            maximumLength: 18
                            validator: RegularExpressionValidator { regularExpression: /[0-9]{0,18}/ }
                            Accessible.name: page.t("special_" + parent.modelData)
                            onTextEdited: page.papers.setSeriesField(page.series.series,
                                parent.modelData, text)
                            onReveal: control => page.reveal(control)
                        }
                    }
                }
            }
            FormCaption {
                visible: !!page.selected.id && page.editorState.editing
                text: page.t("stock_reason")
            }
            MultilineField {
                objectName: "specialReason"
                visible: !!page.selected.id && page.editorState.editing
                text: page.form.reason || ""; readOnly: !page.canEdit; enabled: !page.working
                Accessible.name: page.t("stock_reason")
                onTextChanged: if (activeFocus) page.papers.setField("reason", text)
            }
            Action {
                objectName: "specialSave"; visible: page.canEdit
                text: page.t("special_save"); working: page.working
                onClicked: page.papers.save()
            }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: totalsLayout.implicitHeight + 40
        ColumnLayout {
            id: totalsLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("special_saved_totals") }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 740 ? 2 : 1
                Repeater {
                    model: page.quantityKeys
                    delegate: ColumnLayout {
                        required property string modelData
                        Layout.fillWidth: true
                        FormCaption { text: page.t("special_" + parent.modelData) }
                        Label {
                            objectName: page.summaryName(parent.modelData)
                            Layout.fillWidth: true; color: "#25344b"; font.pixelSize: 24
                            textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
                            text: page.editorState.totals[parent.modelData.replace(/_quantity$/, "_display")]
                        }
                    }
                }
            }
        }
    }
    FormPanel {
        visible: !!page.selected.id
        implicitHeight: historyLayout.implicitHeight + 40
        ColumnLayout {
            id: historyLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("special_history") }
            Repeater {
                model: page.editorState.history
                delegate: Action {
                    required property var modelData
                    objectName: "specialHistoryRevision" + modelData.revision
                    highlighted: page.selected.revision === modelData.revision
                    text: page.t("revision") + " " + modelData.revision + " · "
                        + page.papers.formatTime(modelData.event_at)
                    working: page.working
                    onClicked: page.requestRecord("revision", modelData.revision)
                }
            }
        }
    }
    FormPanel {
        visible: !!page.editorState.station_id
        implicitHeight: reportLayout.implicitHeight + 40
        ColumnLayout {
            id: reportLayout
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("special_report") }
            FormCaption { text: page.t("special_report_hint") }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 740 ? 3 : 1
                Action {
                    id: previewButton
                    objectName: "specialPreview"; text: page.t("stock_preview")
                    enabled: !!page.selected.id && !page.working
                    onClicked: page.papers.preview(page.locale)
                }
                Action {
                    objectName: "specialExportPdf"; text: page.t("stock_export_pdf")
                    enabled: !!page.selected.id && !page.working; highlighted: false
                    onClicked: page.exportReport("pdf")
                }
                Action {
                    objectName: "specialExportCsv"; text: page.t("stock_export_csv")
                    enabled: !!page.selected.id && !page.working; highlighted: false
                    onClicked: page.exportReport("csv")
                }
            }
            FormCaption {
                visible: !!page.editorState.report_text
                text: page.t("stock_preview_language") + " · "
                    + ((page.editorState.report || ({})).locale || page.locale)
            }
            MultilineField {
                objectName: "specialReportPreview"; visible: !!page.editorState.report_text
                text: page.editorState.report_text || ""; readOnly: true
                Accessible.name: page.t("special_report")
                Keys.onEscapePressed: event => {
                    previewButton.forceActiveFocus(Qt.OtherFocusReason); event.accepted = true
                }
            }
            FormCaption {
                objectName: "specialExportPath"; visible: !!page.editorState.export_path
                text: page.t("stock_export_location") + "\n" + (page.editorState.export_path || "")
                wrapMode: Text.WrapAnywhere
            }
        }
    }
    ConfirmationDialog {
        id: discardDialog
        objectName: "specialDiscardDialog"
        title: page.t("discard_changes"); message: page.t("unsaved_special_paper_changes")
        acceptLabel: page.t("discard_changes"); rejectLabel: page.t("keep_editing")
        onConfirmed: page.switchRecord(page.pendingAction, page.pendingId, true)
    }
    FileDialog {
        id: exportDialog
        objectName: "specialExportDialog"
        title: page.t(page.pendingFormat === "pdf" ? "stock_export_pdf" : "stock_export_csv")
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.papers.download(page.pendingFormat, selectedFile.toString(), page.pendingLocale)
    }
}
