pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtCore

ColumnLayout {
    id: page
    required property var countingRounds
    required property var words
    property string locale: "tc"
    readonly property var editorState: countingRounds.state
    readonly property var recountState: countingRounds.recounts.state
    readonly property bool recountProtected: !!recountState.dirty || !!recountState.busy
        || !!recountState.uncertain_save
    readonly property var selected: editorState.selected || ({})
    readonly property var form: editorState.forms || ({})
    readonly property var scope: editorState.scope || ({})
    readonly property bool working: !!editorState.busy
    readonly property bool writer: editorState.role === "counting_officer"
    readonly property bool editable: writer && !working && !editorState.historical
        && !editorState.newer_revision && !!scope.count_ready
        && (!selected.id || selected.status === "draft" || editorState.correction_stage === "f1")
        && (!editorState.correction_stage || editorState.correction_stage === "f1")
        && editorState.dirty_stage !== "f2"
        && (!selected.id || !!selected.source_current || !!editorState.refresh_basis)
        && editorState.context.election && editorState.context.election.status === "active"
    property var candidateRows: []
    property var reasonRows: []
    property string candidateKey: ""
    property string reasonKey: ""
    property var scopeOptions: []
    property var roundOptions: []
    property var historyOptions: []
    property var paperOptions: []
    property var reportOptions: []
    property string selectorKey: ""
    property string paperKey: ""
    property string pendingFormat: "pdf"
    property string pendingLocale: "tc"
    readonly property var selectedPaper: editorState.paper_record || ({})
    signal reveal(var control)
    spacing: 20

    function t(key) { return words[key] || key }
    function exact(row, key) {
        var value = row[key + "_display"]
        if (value !== undefined) return value
        return row[key] === undefined || row[key] === null ? "—" : String(row[key])
    }
    function candidateInput(id) {
        return (editorState.candidate_inputs || []).find(function(row) { return row.candidate_id === id }) || ({})
    }
    function invalidInput(id) {
        return (editorState.invalid_inputs || []).find(function(row) { return row.reason_id === id }) || ({})
    }
    function sourceText(row) {
        if (!row.verified_source) return t("f1_project_reason")
        return t("f1_reference") + " " + (row.source_letter || "")
            + " · " + t("f1_reference_page") + " " + (row.reference_page || "—")
            + (row.reference_printed_page ? " · " + t("f1_printed_page") + " " + row.reference_printed_page : "")
    }
    function time(value) { return value ? countingRounds.formatTime(value) : "—" }
    function indexFor(rows, key, wanted) {
        for (var i = 0; i < rows.length; i++) if (rows[i][key] === wanted) return i
        return -1
    }
    function syncRows() {
        var forms = ["f1", "f2", "f3", "f4", "count"].map(function(form) {
            return {form: form, label: page.t("count_form_" + form)}
        })
        if (!reportFormPicker.popup.visible && JSON.stringify(reportOptions) !== JSON.stringify(forms))
            reportOptions = forms
        var candidates = (editorState.candidate_inputs || []).map(function(row) {
            return {candidate_id: row.candidate_id, name: row.name, ballot_number: row.ballot_number}
        })
        var ck = JSON.stringify(candidates)
        if (ck !== candidateKey) { candidateKey = ck; candidateRows = candidates }
        var reasons = (editorState.invalid_inputs || []).map(function(row) {
            return {reason_id: row.reason_id, reason_revision: row.reason_revision,
                label_tc: row.label_tc, label_sc: row.label_sc, label_en: row.label_en,
                verified_source: row.verified_source, source_letter: row.source_letter,
                source_english: row.source_english, reference_page: row.reference_page,
                reference_printed_page: row.reference_printed_page,
                explanation_required: row.explanation_required, current_catalog: row.current_catalog}
        })
        var rk = JSON.stringify(reasons)
        if (rk !== reasonKey) { reasonKey = rk; reasonRows = reasons }
        var scopes = [{id: 0, label: t("f1_choose_scope")}].concat((editorState.scopes || []).map(function(row) {
            return {id: row.id, label: row.reference + " · " + t("revision") + " " + row.revision
                + " · " + t(row.count_ready ? "f1_scope_ready" : "f1_scope_unready")}
        }))
        var rounds = (editorState.rounds || []).map(function(row) {
            return {id: row.id, label: t("f1_round") + " " + row.round_number
                + " · " + t("revision") + " " + row.revision}
        })
        if (!rounds.length) rounds = [{id: 0, label: t("f1_initial_round")}]
        var history = (editorState.history || []).map(function(row) {
            return {revision: row.revision, label: t("revision") + " " + row.revision + " · " + t(row.status)}
        })
        var sk = JSON.stringify([scopes, rounds, history])
        if (sk !== selectorKey) {
            selectorKey = sk; scopeOptions = scopes; roundOptions = rounds; historyOptions = history
        }
        var papers = [{id: 0, label: t("paper_reentry_none")}].concat(
            (editorState.paper_records || []).map(function(row) {
                return {id: row.id, label: row.paper_reference + " · "
                    + page.time(row.original_event_at)}
            }))
        var pk = JSON.stringify(papers)
        if (pk !== paperKey) { paperKey = pk; paperOptions = papers }
    }
    function exportReport(format) {
        pendingFormat = format; pendingLocale = locale
        exportDialog.nameFilters = format === "pdf" ? ["PDF (*.pdf)"] : ["CSV (*.csv)"]
        exportDialog.defaultSuffix = format
        // Native currentFolder can be an absolute path URL without a file scheme.
        // Resolve it before passing the next suggested filename to the native panel.
        exportDialog.selectedFile = Qt.resolvedUrl(exportDialog.currentFolder.toString() + "/" + (editorState.report_form || "f1") + "-round-"
            + selected.id + "-revision-" + selected.revision + "-" + locale + "." + format)
        exportDialog.open()
    }
    function moveFocus(field, forward) {
        var next = field.nextItemInFocusChain(forward)
        if (next) next.forceActiveFocus(forward ? Qt.TabFocusReason : Qt.BacktabFocusReason)
    }
    onLocaleChanged: syncRows()
    onWordsChanged: syncRows()
    Component.onCompleted: syncRows()
    Connections {
        target: page.countingRounds
        function onStateChanged() { page.syncRows() }
    }

    component Heading: Label {
        textFormat: Text.PlainText; wrapMode: Text.WordWrap
        font.pixelSize: 20; font.weight: Font.Medium; color: "#25344b"
        Layout.fillWidth: true
    }
    component Detail: ColumnLayout {
        id: detail
        required property string caption
        required property string value
        Layout.fillWidth: true
        spacing: 6
        FormCaption { text: detail.caption }
        Label {
            objectName: detail.objectName ? detail.objectName + "Value" : ""
            text: detail.value; textFormat: Text.PlainText; wrapMode: Text.WrapAnywhere
            font.pixelSize: 15; color: "#25344b"; Layout.fillWidth: true
        }
    }
    component Entry: FormField {
        readOnly: !page.editable
        working: page.working
        onReveal: control => page.reveal(control)
    }
    component Notes: TextArea {
        id: field
        property string caption: ""
        Layout.fillWidth: true
        implicitHeight: Math.max(92, contentHeight + topPadding + bottomPadding)
        textFormat: TextEdit.PlainText; wrapMode: TextEdit.WordWrap
        clip: true; selectByMouse: true; readOnly: !page.editable; enabled: !page.working
        leftPadding: 12; rightPadding: 12; topPadding: 12; bottomPadding: 12; topInset: 0
        Accessible.name: caption
        Keys.priority: Keys.BeforeItem
        Keys.onTabPressed: event => { page.moveFocus(field, true); event.accepted = true }
        Keys.onBacktabPressed: event => { page.moveFocus(field, false); event.accepted = true }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() {
            if (field.activeFocus) page.reveal(field)
        })
        background: Rectangle {
            radius: 8; color: "white"; border.color: field.activeFocus ? "#1967d2" : "#a7b2c2"
            border.width: field.activeFocus ? 2 : 1
        }
    }
    component Action: FormButton {
        id: button
        Layout.fillWidth: true
        implicitHeight: Math.max(48, buttonText.implicitHeight + 24)
        contentItem: Text {
            id: buttonText
            text: button.text; textFormat: Text.PlainText; font: button.font
            wrapMode: Text.WordWrap; horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: button.enabled ? (button.highlighted ? "white" : "#1967d2") : "#8a96a8"
        }
        onReveal: control => page.reveal(control)
    }
    component Picker: ComboBox {
        id: picker
        Layout.fillWidth: true; textRole: "label"
        implicitHeight: Math.max(48, pickerText.implicitHeight + 24)
        contentItem: Text {
            id: pickerText
            text: picker.displayText; font: picker.font; textFormat: Text.PlainText
            wrapMode: Text.WordWrap; color: "#25344b"; leftPadding: 12; rightPadding: 40
            verticalAlignment: Text.AlignVCenter
        }
        delegate: ItemDelegate {
            required property var modelData
            width: picker.width
            implicitHeight: Math.max(48, optionText.implicitHeight + 24)
            contentItem: Text {
                id: optionText
                text: parent.modelData.label; textFormat: Text.PlainText; wrapMode: Text.WordWrap
                color: "#25344b"
            }
        }
        onActiveFocusChanged: if (activeFocus) Qt.callLater(function() { page.reveal(picker) })
    }

    RowLayout {
        Layout.fillWidth: true
        Heading { objectName: "countingRoundsTitle"; text: page.t("f1_title"); font.pixelSize: 28 }
        BusyIndicator {
            running: page.editorState.busy || page.editorState.refreshing
            visible: running; implicitWidth: 28; implicitHeight: 28
            Accessible.name: page.t("loading")
        }
        FormButton {
            objectName: "f1Refresh"; text: page.t("refresh"); flat: true; highlighted: false
            enabled: !page.working && !!page.editorState.station_id
            onClicked: page.countingRounds.refresh()
            onReveal: control => page.reveal(control)
        }
    }
    FormCaption { text: page.t("f1_intro") }
    FormNotice {
        objectName: "f1Notice"; words: page.words
        error: page.editorState.error; notice: page.editorState.notice
        autoReveal: !discardDialog.visible
        onReveal: control => page.reveal(control)
    }
    FormCaption {
        objectName: "f1NewerWarning"
        visible: !!page.editorState.newer_revision; text: page.t("f1_newer"); color: "#8a5c16"
    }
    FormCaption { visible: !page.writer; text: page.t("f1_read_only") }
    FormCaption { visible: !!page.editorState.historical; text: page.t("f1_historical") }
    FormPanel {
        implicitHeight: selectors.implicitHeight + 40
        ColumnLayout {
            id: selectors
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            FormCaption { text: page.t("f1_scope") }
            Picker {
                objectName: "countingRoundsScope"; model: page.scopeOptions
                currentIndex: page.indexFor(page.scopeOptions, "id", page.editorState.selected_scope_id)
                enabled: !page.working && !page.editorState.dirty && !page.recountProtected
                Accessible.name: page.t("f1_scope")
                onActivated: index => {
                    var row = model[index]
                    if (row && row.id) page.countingRounds.selectScope(row.id)
                }
            }
            FormCaption { text: page.t("f1_round") }
            FormCaption {
                objectName: "f1EditingScopeRevision"
                visible: !!page.editorState.selected_scope_id
                text: page.t("f1_edit_scope_basis") + " #" + page.editorState.selected_scope_id
                    + " · " + page.t("revision") + " " + (page.editorState.edit_scope_revision || "—")
            }
            Picker {
                objectName: "countingRoundsRound"; model: page.roundOptions
                currentIndex: page.indexFor(page.roundOptions, "id", page.selected.id || 0)
                enabled: !page.working && !page.editorState.dirty && !page.recountProtected && page.roundOptions.length > 1
                Accessible.name: page.t("f1_round")
                onActivated: index => {
                    var row = model[index]
                    if (row && row.id) page.countingRounds.selectRound(row.id)
                }
            }
            FormCaption { text: page.t("f1_history") }
            Picker {
                objectName: "countingRoundHistory"; model: page.historyOptions
                currentIndex: page.indexFor(page.historyOptions, "revision", page.selected.revision || 0)
                enabled: !page.working && !page.editorState.dirty && !page.recountProtected && page.historyOptions.length > 0
                Accessible.name: page.t("f1_history")
                onActivated: index => {
                    if (model[index]) page.countingRounds.loadRevision(model[index].revision)
                }
            }
            Action {
                objectName: "f1Reload"; text: page.t("f1_reload"); highlighted: false
                enabled: !page.working && !page.recountProtected && !!page.editorState.station_id
                onClicked: {
                    if (page.editorState.dirty || page.editorState.newer_revision) discardDialog.open()
                    else page.countingRounds.reload()
                }
            }
        }
    }
    LocalRecountsPanel {
        objectName: "localRecountsPanel"
        visible: !!page.editorState.selected_scope_id
        enabled: !page.editorState.busy && !page.editorState.dirty
        recounts: page.countingRounds.recounts
        words: page.words
        onReveal: control => page.reveal(control)
    }
    FormPanel {
        objectName: "countPaperReentryPanel"
        visible: !!page.selected.id && page.selected.status === "draft"
            && page.writer && !page.editorState.historical
        implicitHeight: paperColumn.implicitHeight + 40
        ColumnLayout {
            id: paperColumn
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("paper_reentry_title") }
            FormCaption { text: page.t("paper_reentry_hint") }
            Picker {
                objectName: "countRoundPaperRecord"
                model: page.paperOptions
                currentIndex: page.indexFor(page.paperOptions, "id", page.selectedPaper.id || 0)
                enabled: !page.working && !page.editorState.refreshing
                    && !page.editorState.paper_loading
                    && !page.editorState.uncertain_save && !page.editorState.paper_binding_locked
                Accessible.name: page.t("paper_reentry_reference")
                onActivated: index => {
                    if (model[index]) page.countingRounds.selectPaperRecord(model[index].id)
                }
            }
            FormCaption {
                objectName: "countRoundPaperReference"
                visible: !!page.selectedPaper.id
                text: page.t("paper_reentry_reference") + " · "
                    + (page.selectedPaper.paper_reference || "")
            }
            FormCaption {
                objectName: "countRoundPaperOriginalTime"
                visible: !!page.selectedPaper.id
                text: page.t("paper_reentry_original_at") + " · "
                    + page.time(page.selectedPaper.original_event_at)
            }
            FormCaption {
                visible: page.editorState.error_origin === "read" && !!page.editorState.error
                text: page.t("paper_reentry_load_failed")
                color: "#8a5c16"
            }
            RowLayout {
                Layout.fillWidth: true
                Action {
                    objectName: "countRoundPaperRefresh"
                    text: page.t("paper_reentry_refresh")
                    highlighted: false
                    enabled: !page.working && !page.editorState.refreshing
                    && !page.editorState.paper_loading
                    onClicked: page.countingRounds.refreshPaperRecords()
                }
                Action {
                    objectName: "countRoundPaperClear"
                    text: page.t("paper_reentry_clear")
                    highlighted: false
                    enabled: !!page.selectedPaper.id && !page.working
                        && !page.editorState.paper_loading
                        && !page.editorState.uncertain_save
                        && !page.editorState.paper_binding_locked
                    onClicked: page.countingRounds.selectPaperRecord(0)
                }
            }
        }
    }
    FormPanel {
        visible: page.writer && !!page.selected.id && !page.editorState.historical
            && (page.selected.status !== "draft" || !page.selected.source_current
                || !!page.editorState.correction_stage)
        implicitHeight: corrections.implicitHeight + 40
        ColumnLayout {
            id: corrections
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("count_correction_title") }
            FormCaption { text: page.t("count_correction_hint") }
            FormCaption {
                objectName: "countCorrectionMode"
                visible: !!page.editorState.correction_stage
                text: page.t("count_correction_mode") + " · "
                    + (page.editorState.correction_stage || "").toUpperCase()
                    + " · " + page.t("revision") + " " + page.editorState.edit_scope_revision
            }
            FormCaption {
                visible: !!page.editorState.refresh_basis
                text: page.t("count_refresh_basis_hint")
                color: "#8a5c16"
            }
            GridLayout {
                Layout.fillWidth: true
                columns: page.width > 700 ? 2 : 1
                columnSpacing: 12; rowSpacing: 12
                Action {
                    objectName: "countCorrectF1"
                    text: page.t("count_correct_f1")
                    visible: !page.editorState.correction_stage && !!page.selected.source_current
                        && page.selected.status !== "draft"
                    enabled: !page.working && !page.editorState.dirty && !page.recountProtected && !page.editorState.newer_revision
                        && page.editorState.context.election
                        && page.editorState.context.election.status === "active"
                    onClicked: page.countingRounds.startCorrection("f1", false)
                }
                Action {
                    objectName: "countCorrectF2"
                    text: page.t("count_correct_f2")
                    visible: !page.editorState.correction_stage && !!page.selected.source_current
                        && !!page.selected.f1_complete && page.selected.status !== "draft"
                    enabled: !page.working && !page.editorState.dirty && !page.recountProtected && !page.editorState.newer_revision
                        && page.editorState.context.election
                        && page.editorState.context.election.status === "active"
                    onClicked: page.countingRounds.startCorrection("f2", false)
                }
                Action {
                    objectName: "countRefreshBasisCorrection"
                    text: page.t("count_refresh_basis")
                    visible: !page.editorState.correction_stage && !page.selected.source_current
                    enabled: !page.working && !page.editorState.dirty && !page.recountProtected && !page.editorState.newer_revision
                        && !!page.editorState.latest_scope.count_ready
                        && page.editorState.context.election
                        && page.editorState.context.election.status === "active"
                    onClicked: refreshBasisDialog.open()
                }
                Action {
                    objectName: "countCancelCorrection"
                    text: page.t("count_cancel_correction")
                    visible: !!page.editorState.correction_stage
                    enabled: !page.working && !page.editorState.uncertain_save
                    onClicked: cancelCorrectionDialog.open()
                }
            }
        }
    }
    FormCaption {
        objectName: "countDecisionsChanged"
        visible: !!page.editorState.decisions_changed
        text: page.t("count_decisions_changed")
    }
    FormCaption {
        visible: !!page.editorState.selected_scope_id && !page.selected.id
        text: page.t("f1_no_round")
    }
    FormCaption {
        visible: !!page.editorState.selected_scope_id && !page.scope.count_ready
        text: page.t("count_scope_not_ready"); color: "#8a5c16"
    }
    FormPanel {
        visible: !!page.editorState.selected_scope_id && !page.selected.id
        implicitHeight: unsavedBasis.implicitHeight + 40
        ColumnLayout {
            id: unsavedBasis
            anchors.fill: parent; anchors.margins: 20; spacing: 12
            Heading { text: page.t("f1_scope_basis") }
            FormCaption { text: page.t("f1_estimate_note") }
            Detail {
                caption: page.t("f1_scope_stock_estimate")
                value: page.exact(page.scope, "estimated_box_from_stock_quantity")
            }
            Detail {
                caption: page.t("f1_scope_turnout_estimate")
                value: page.exact(page.scope, "estimated_box_from_turnout_quantity")
            }
            Repeater {
                model: page.scope.box_basis || []
                FormCaption {
                    required property var modelData
                    text: modelData.box_reference + " · " + modelData.origin.code
                        + " · " + page.t("revision") + " " + modelData.revision
                }
            }
            Repeater {
                model: page.scope.accounting_basis || []
                FormCaption {
                    required property var modelData
                    text: modelData.context.station.code + " · P(18) #" + modelData.id
                        + " · " + page.t("revision") + " " + modelData.revision
                }
            }
        }
    }
    ColumnLayout {
        visible: !!page.editorState.selected_scope_id
        Layout.fillWidth: true; spacing: 20
        FormPanel {
            implicitHeight: entry.implicitHeight + 40
            ColumnLayout {
                id: entry
                anchors.fill: parent; anchors.margins: 20; spacing: 14
                FormCaption { text: page.t("f1_event_at") }
                Entry {
                    objectName: "f1EventAt"; text: page.form.event_at || ""
                    placeholderText: "YYYY-MM-DD HH:MM:SS.ffffff"
                    Accessible.name: page.t("f1_event_at")
                    onTextEdited: page.countingRounds.setField("event_at", text)
                }
                FormCaption { text: page.t("f1_time_hint") }
                Heading { text: page.t("f1_candidates") }
                Repeater {
                    model: page.candidateRows
                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true; spacing: 6
                        FormCaption {
                            objectName: "f1CandidateLabel_" + parent.modelData.candidate_id
                            text: parent.modelData.ballot_number + " · " + parent.modelData.name
                        }
                        Entry {
                            objectName: "f1CandidateQuantity_" + parent.modelData.candidate_id
                            text: page.candidateInput(parent.modelData.candidate_id).quantity || ""
                            Accessible.name: parent.modelData.name + " · " + page.t("f1_quantity")
                            onTextEdited: page.countingRounds.setCandidateQuantity(parent.modelData.candidate_id, text)
                        }
                    }
                }
                Heading { text: page.t("f1_invalid") }
                FormCaption { text: page.t("f1_catalog_hint") }
                Repeater {
                    model: page.reasonRows
                    ColumnLayout {
                        id: reasonRow
                        required property var modelData
                        Layout.fillWidth: true; spacing: 8
                        FormCaption {
                            objectName: "f1InvalidLabel_" + reasonRow.modelData.reason_id
                            text: reasonRow.modelData["label_" + page.locale] || ""
                        }
                        FormCaption {
                            text: page.sourceText(reasonRow.modelData)
                            color: "#52647d"
                        }
                        FormCaption {
                            visible: !!reasonRow.modelData.verified_source
                            text: page.t("f1_translation_note") + "\n" + (reasonRow.modelData.source_english || "")
                        }
                        FormCaption {
                            visible: !reasonRow.modelData.current_catalog
                            text: page.t("f1_retired_reason"); color: "#8a5c16"
                        }
                        Entry {
                            objectName: "f1InvalidQuantity_" + reasonRow.modelData.reason_id
                            text: page.invalidInput(reasonRow.modelData.reason_id).quantity || ""
                            Accessible.name: (reasonRow.modelData["label_" + page.locale] || "")
                                + " · " + page.t("f1_quantity")
                            onTextEdited: page.countingRounds.setInvalidQuantity(reasonRow.modelData.reason_id, text)
                        }
                        FormCaption { visible: !!reasonRow.modelData.explanation_required; text: page.t("f1_explanation") }
                        Notes {
                            objectName: "f1InvalidExplanation_" + reasonRow.modelData.reason_id
                            visible: !!reasonRow.modelData.explanation_required
                                || !!page.invalidInput(reasonRow.modelData.reason_id).explanation
                            caption: page.t("f1_explanation")
                            text: page.invalidInput(reasonRow.modelData.reason_id).explanation || ""
                            onTextChanged: if (activeFocus) page.countingRounds.setInvalidExplanation(reasonRow.modelData.reason_id, text)
                        }
                    }
                }
                FormCaption { text: page.t("f1_questionable") }
                Entry {
                    objectName: "f1QuestionableQuantity"; text: page.form.questionable_quantity || ""
                    Accessible.name: page.t("f1_questionable")
                    onTextEdited: page.countingRounds.setField("questionable_quantity", text)
                }
                FormCaption { text: page.t("f1_actual") }
                Entry {
                    objectName: "f1ActualCountedQuantity"; text: page.form.actual_counted_quantity || ""
                    Accessible.name: page.t("f1_actual")
                    onTextEdited: page.countingRounds.setField("actual_counted_quantity", text)
                }
                FormCaption { text: page.t("f1_notes") }
                Notes {
                    objectName: "f1Notes"; caption: page.t("f1_notes"); text: page.form.notes || ""
                    onTextChanged: if (activeFocus) page.countingRounds.setField("notes", text)
                }
                FormCaption {
                    text: page.t(page.editorState.correction_stage === "f1"
                        ? "count_correction_reason_label" : "f1_amendment_reason")
                }
                Notes {
                    objectName: "f1AmendmentReason"
                    caption: page.t(page.editorState.correction_stage === "f1"
                        ? "count_correction_reason_label" : "f1_amendment_reason")
                    text: page.form.amendment_reason || ""
                    onTextChanged: if (activeFocus) page.countingRounds.setField("amendment_reason", text)
                }
                Action {
                    objectName: "f1Save"; text: page.t(page.editorState.correction_stage === "f1"
                        ? "count_save_correction" : "f1_save"); visible: page.writer
                    enabled: page.editable || (page.writer && !page.working && !!page.editorState.uncertain_save)
                    working: page.working
                    onClicked: {
                        if (page.selected.f2 && (page.selected.status === "draft"
                                || page.editorState.correction_stage === "f1"))
                            discardF2Dialog.open()
                        else
                            page.countingRounds.save()
                    }
                }
            }
        }
    }
    FormPanel {
        visible: !!page.selected.id
        implicitHeight: saved.implicitHeight + 40
        ColumnLayout {
            id: saved
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t("f1_saved_summary") }
            FormCaption {
                objectName: "f1RoundRevision"
                text: page.t("f1_round") + " " + (page.selected.round_number || "—")
                    + " · " + page.t("revision") + " " + (page.selected.revision || "—")
                    + " · " + page.t(page.selected.status || "draft")
            }
            FormCaption { text: page.t(page.selected.f1_complete ? "f1_complete" : "f1_incomplete") }
            FormCaption {
                visible: !!page.selected.id && !page.selected.source_current
                text: page.t("count_round_basis_stale"); color: "#8a5c16"
            }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 700 ? 2 : 1
                columnSpacing: 20; rowSpacing: 16
                Repeater {
                    model: ["initial_valid_quantity", "clearly_invalid_quantity", "questionable_quantity",
                            "actual_counted_quantity", "initial_accounted_quantity"]
                    Detail {
                        required property string modelData
                        objectName: "f1Saved_" + modelData
                        caption: page.t("f1_" + modelData); value: page.exact(page.selected, modelData)
                    }
                }
            }
            FormCaption { text: page.t("f1_event_at") + " · " + page.time(page.selected.event_at) }
            FormCaption { text: page.t("f1_entered_at") + " · " + page.time(page.selected.entered_at) }
            Repeater {
                model: page.selected.blockers || []
                FormCaption {
                    required property var modelData
                    text: page.t(modelData.code); color: "#8a5c16"
                }
            }
            Heading { text: page.t("f1_saved_reasons") }
            Repeater {
                model: page.selected.invalid_papers || []
                FormCaption {
                    required property var modelData
                    text: (modelData["label_" + page.locale] || "") + " · " + page.exact(modelData, "quantity")
                        + (modelData.explanation ? " · " + modelData.explanation : "")
                }
            }
            Heading { text: page.t("f1_scope_basis") }
            FormCaption {
                objectName: "f1ScopeRevision"
                text: "#" + page.selected.scope_id + " · " + page.t("revision") + " " + page.selected.scope_revision
            }
            FormCaption { text: page.t("f1_estimate_note") }
            Repeater {
                model: (page.selected.scope_basis || {}).box_basis || []
                FormCaption {
                    required property var modelData
                    text: modelData.box_reference + " · " + modelData.origin.code
                        + " · " + page.t("revision") + " " + modelData.revision
                }
            }
            Repeater {
                model: (page.selected.scope_basis || {}).accounting_basis || []
                FormCaption {
                    required property var modelData
                    text: modelData.context.station.code + " · P(18) #" + modelData.id
                        + " · " + page.t("revision") + " " + modelData.revision
                }
            }
        }
    }
    CountOutcomesPanel {
        countingRounds: page.countingRounds
        words: page.words
        locale: page.locale
        onReveal: control => page.reveal(control)
    }
    FormPanel {
        visible: !!page.selected.id
        implicitHeight: reports.implicitHeight + 40
        ColumnLayout {
            id: reports
            anchors.fill: parent; anchors.margins: 20; spacing: 14
            Heading { text: page.t(page.editorState.report_form === "f1" ? "f1_report" : "count_reports") }
            FormCaption { text: page.t("count_report_form") }
            Picker {
                id: reportFormPicker
                objectName: "countReportForm"
                model: page.reportOptions
                currentIndex: page.indexFor(page.reportOptions, "form", page.editorState.report_form)
                displayText: page.t("count_form_" + (page.editorState.report_form || "f1"))
                Accessible.name: page.t("count_report_form")
                enabled: !page.working && !page.editorState.dirty && !page.recountProtected
                onActivated: index => {
                    if (index >= 0) page.countingRounds.selectReportForm(model[index].form)
                }
            }
            GridLayout {
                Layout.fillWidth: true; columns: page.width > 800 ? 3 : 1
                columnSpacing: 12; rowSpacing: 12
                Action {
                    objectName: "f1Preview"; text: page.t(page.editorState.report_form === "f1" ? "f1_preview" : "count_preview")
                    enabled: !page.working && !page.editorState.dirty && !page.recountProtected
                    onClicked: page.countingRounds.preview(page.locale)
                }
                Action {
                    objectName: "f1ExportPdf"; text: page.t("stock_export_pdf")
                    enabled: !page.working && !page.editorState.dirty && !page.recountProtected
                    onClicked: page.exportReport("pdf")
                }
                Action {
                    objectName: "f1ExportCsv"; text: page.t("stock_export_csv")
                    enabled: !page.working && !page.editorState.dirty && !page.recountProtected
                    onClicked: page.exportReport("csv")
                }
            }
            Label {
                objectName: "f1ReportPreview"
                visible: page.editorState.report.locale === page.locale
                text: page.editorState.report_text; textFormat: Text.PlainText
                wrapMode: Text.WrapAnywhere; color: "#25344b"; Layout.fillWidth: true
            }
            FormCaption { visible: !!page.editorState.export_path; text: page.editorState.export_path || "" }
        }
    }
    ConfirmationDialog {
        id: discardDialog
        objectName: "f1DiscardDialog"; focus: true
        message: page.t("f1_discard")
        acceptLabel: page.t("discard_changes"); rejectLabel: page.t("keep_editing")
        onConfirmed: page.countingRounds.discardAndReload()
    }
    ConfirmationDialog {
        id: discardF2Dialog
        objectName: "f1DiscardF2Dialog"
        focus: true
        message: page.t("f1_discard_f2_title") + "\n" + page.t("f1_discard_f2_message")
        acceptLabel: page.t("f1_discard_f2_confirm")
        rejectLabel: page.t("keep_editing")
        onConfirmed: page.countingRounds.saveDiscardingF2()
    }
    ConfirmationDialog {
        id: refreshBasisDialog
        objectName: "countRefreshBasisDialog"
        message: page.t("count_refresh_basis_hint") + "\n"
            + page.t("revision") + " " + page.editorState.latest_scope.revision
        acceptLabel: page.t("count_refresh_basis")
        rejectLabel: page.t("keep_editing")
        onConfirmed: page.countingRounds.startCorrection("f1", true)
    }
    ConfirmationDialog {
        id: cancelCorrectionDialog
        objectName: "countCancelCorrectionDialog"
        message: page.t("count_cancel_correction_hint")
        acceptLabel: page.t("count_cancel_correction")
        rejectLabel: page.t("keep_editing")
        onConfirmed: page.countingRounds.cancelCorrection()
    }
    FileDialog {
        id: exportDialog
        objectName: "countReportExportDialog"
        fileMode: FileDialog.SaveFile
        currentFolder: StandardPaths.writableLocation(StandardPaths.DocumentsLocation)
        onAccepted: page.countingRounds.exportStatement(
            page.pendingFormat, page.pendingLocale, selectedFile.toString())
    }
}
