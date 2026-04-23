{{/*
Expand the name of the chart.
*/}}
{{- define "keycloak-baseline.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "keycloak-baseline.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "keycloak-baseline.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Common labels
*/}}
{{- define "keycloak-baseline.labels" -}}
helm.sh/chart: {{ include "keycloak-baseline.chart" . }}
{{ include "keycloak-baseline.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selector labels
*/}}
{{- define "keycloak-baseline.selectorLabels" -}}
app.kubernetes.io/name: {{ include "keycloak-baseline.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Create the name of the realm ConfigMap.
*/}}
{{- define "keycloak-baseline.realm.configMapName" -}}
{{- if .Values.realm.configMapName -}}
{{- .Values.realm.configMapName -}}
{{- else -}}
keycloak-baseline-realm
{{- end -}}
{{- end -}}

{{/*
Generate realm JSON for Keycloak import.
*/}}
{{- define "keycloak-baseline.realm.json" -}}
{
  "realm": "{{ .Values.realm.name }}",
  "enabled": true,
  "displayName": "{{ .Values.realm.displayName | replace "\"" "\\\"" }}",
  "displayNameHtml": "{{ .Values.realm.displayNameHtml | replace "\"" "\\\"" }}",
  "sslRequired": "{{ .Values.realm.sslRequired }}",
  "registrationAllowed": {{ .Values.realm.registration.enabled }},
  "registrationEmailAsUsername": {{ .Values.realm.registration.emailAsUsername }},
  "verifyEmail": {{ .Values.realm.registration.verifyEmail }},
  "resetPasswordAllowed": {{ .Values.realm.registration.resetPasswordAllowed }},
  "loginTheme": "{{ .Values.realm.themes.login }}",
  "accountTheme": "{{ .Values.realm.themes.account }}",
  "adminTheme": "{{ .Values.realm.themes.admin }}",
  "emailTheme": "{{ .Values.realm.themes.email }}",
  "passwordPolicy": "{{ .Values.realm.passwordPolicy }}",
  "accessTokenLifespan": {{ .Values.realm.accessTokenLifespan }},
  "ssoSessionMaxLifespan": {{ .Values.realm.ssoSession.max }},
  "ssoSessionIdleTimeout": {{ .Values.realm.ssoSession.idleTimeout }},
  "clients": [
    {{- $firstClient := true }}
    {{- /* Process clients from .Values.clients */ -}}
    {{- range $idx, $client := .Values.clients }}
    {{- if not $firstClient }},{{ end }}
    {{- $firstClient = false }}
    {
      "clientId": "{{ $client.clientId | default $client.name }}",
      "name": "{{ $client.displayName | default $client.name }}",
      "description": "{{ $client.description | replace "\"" "\\\"" }}",
      "enabled": true,
      "alwaysDisplayInConsole": {{ $client.alwaysDisplayInConsole | default false }},
      "rootUrl": "{{ $client.baseUrl }}",
      "baseUrl": "{{ $client.baseUrl }}",
      "redirectUris": [
        {{- $firstUri := true }}
        {{- range $uri := $client.redirectUris }}
        {{- if not $firstUri }},{{ end }}
        "{{ $uri }}"
        {{- $firstUri = false }}
        {{- end }}
      ],
      "webOrigins": [
        {{- $firstOrigin := true }}
        {{- range $origin := $client.webOrigins }}
        {{- if not $firstOrigin }},{{ end }}
        "{{ $origin }}"
        {{- $firstOrigin = false }}
        {{- end }}
      ],
      "publicClient": {{ $client.publicClient | default false }},
      "standardFlowEnabled": {{ $client.standardFlowEnabled | default true }},
      "implicitFlowEnabled": {{ $client.implicitFlowEnabled | default false }},
      "directAccessGrantsEnabled": {{ $client.directAccessGrantsEnabled | default false }},
      "serviceAccountsEnabled": {{ $client.serviceAccountsEnabled | default false }},
      "protocol": "openid-connect"
      {{- if $client.pkce }},
      "attributes": {
        "pkce.code.challenge.method": "{{ $client.pkce }}"
      }
      {{- end }}
    }
    {{- end }}
    {{- /* Process service accounts as clients */ -}}
    {{- range $name, $sa := .Values.serviceAccounts }}
    {{- if $sa.enabled }}
    {{- if not $firstClient }},{{ end }}
    {{- $firstClient = false }}
    {
      "clientId": "{{ $sa.clientId }}",
      "name": "{{ $sa.name }}",
      "description": "{{ $sa.description | replace "\"" "\\\"" }}",
      "enabled": true,
      "publicClient": false,
      "standardFlowEnabled": false,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": true,
      "protocol": "openid-connect",
      "defaultClientScopes": [
        {{- $firstScope := true }}
        {{- range $scope := $sa.scopes }}
        {{- if not $firstScope }},{{ end }}
        "{{ $scope }}"
        {{- $firstScope = false }}
        {{- end }}
      ]
    }
    {{- end }}
    {{- end }}
  ],
  "roles": {
    "realm": [
      {{- $firstRole := true }}
      {{- if .Values.realmRoles.platform }}
      {{- range $role := .Values.realmRoles.platform }}
      {{- if not $firstRole }},{{ end }}
      {
        "name": "{{ $role.name }}",
        "description": "{{ $role.description | replace "\"" "\\\"" }}"
        {{- if $role.composite }},
        "composite": true,
        "composites": {
          "realm": [
            {{- $firstComposite := true }}
            {{- range $composite := $role.composites }}
            {{- if not $firstComposite }},{{ end }}
            "{{ $composite }}"
            {{- $firstComposite = false }}
            {{- end }}
          ]
        }
        {{- end }}
      }
      {{- $firstRole = false }}
      {{- end }}
      {{- end }}
      {{- if .Values.realmRoles.serviceRoles }}
      {{- range $serviceName, $serviceRoles := .Values.realmRoles.serviceRoles }}
      {{- range $role := $serviceRoles }}
      {{- if not $firstRole }},{{ end }}
      {
        "name": "{{ $role.name }}",
        "description": "{{ $role.description | replace "\"" "\\\"" }}"
        {{- if $role.composite }},
        "composite": true,
        "composites": {
          "realm": [
            {{- $firstComposite := true }}
            {{- range $composite := $role.composites }}
            {{- if not $firstComposite }},{{ end }}
            "{{ $composite }}"
            {{- $firstComposite = false }}
            {{- end }}
          ]
        }
        {{- end }}
      }
      {{- $firstRole = false }}
      {{- end }}
      {{- end }}
      {{- end }}
    ]
  },
  "groups": [
    {{- $firstGroup := true }}
    {{- if .Values.groups.topLevel }}
    {{- range $group := .Values.groups.topLevel }}
    {{- if not $firstGroup }},{{ end }}
    {
      "name": "{{ $group.name }}",
      "path": "/{{ $group.name }}",
      "attributes": {
        "description": ["{{ $group.description | replace "\"" "\\\"" }}"]
      },
      "subGroups": [
        {{- $firstSubGroup := true }}
        {{- range $subGroup := $group.subGroups }}
        {{- if not $firstSubGroup }},{{ end }}
        {
          "name": "{{ $subGroup.name }}",
          "path": "/{{ $group.name }}/{{ $subGroup.name }}",
          "attributes": {
            "description": ["{{ $subGroup.description | replace "\"" "\\\"" }}"]
          },
          "subGroups": [
            {{- $firstSubSubGroup := true }}
            {{- range $subSubGroup := $subGroup.subGroups }}
            {{- if not $firstSubSubGroup }},{{ end }}
            {
              "name": "{{ $subSubGroup.name }}",
              "path": "/{{ $group.name }}/{{ $subGroup.name }}/{{ $subSubGroup.name }}",
              "attributes": {
                "description": ["{{ $subSubGroup.description | replace "\"" "\\\"" }}"]
              }
            }
            {{- $firstSubSubGroup = false }}
            {{- end }}
          ]
        }
        {{- $firstSubGroup = false }}
        {{- end }}
      ]
    }
    {{- $firstGroup = false }}
    {{- end }}
    {{- end }}
  ],
  "clientScopes": [
    {{- $firstScope := true }}
    {{- /* Standard OIDC scopes */ -}}
    {{- range $scope := .Values.clientScopes.standard }}
    {{- if not $firstScope }},{{ end }}
    {{- $firstScope = false }}
    {
      "name": "{{ $scope.name }}",
      "description": "{{ $scope.description | replace "\"" "\\\"" }}",
      "protocol": "{{ $scope.protocol }}",
      "type": "{{ $scope.type }}",
      "enabled": {{ $scope.enabled }}
    }
    {{- end }}
    {{- /* Platform custom scopes */ -}}
    {{- range $scope := .Values.clientScopes.platform }}
    {{- if not $firstScope }},{{ end }}
    {{- $firstScope = false }}
    {
      "name": "{{ $scope.name }}",
      "description": "{{ $scope.description | replace "\"" "\\\"" }}",
      "protocol": "{{ $scope.protocol }}",
      "type": "{{ $scope.type }}",
      "enabled": {{ $scope.enabled }}
      {{- if $scope.mappers }},
      "protocolMappers": [
        {{- $firstMapper := true }}
        {{- range $mapper := $scope.mappers }}
        {{- if not $firstMapper }},{{ end }}
        {{- $firstMapper = false }}
        {
          "name": "{{ $mapper.name }}",
          "protocol": "{{ $scope.protocol }}",
          "protocolMapper": "{{ $mapper.type }}",
          "consentRequired": false,
          "config": {
            {{- $firstConfig := true }}
            {{- range $key, $value := $mapper.config }}
            {{- if not $firstConfig }},{{ end }}
            "{{ $key }}": "{{ $value }}"
            {{- $firstConfig = false }}
            {{- end }}
          }
        }
        {{- end }}
      ]
      {{- end }}
    }
    {{- end }}
  ]
}
{{- end -}}