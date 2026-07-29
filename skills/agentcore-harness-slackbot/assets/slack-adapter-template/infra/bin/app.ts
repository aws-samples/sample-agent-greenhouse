#!/usr/bin/env node
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import { SlackAdapterStack } from "../lib/slack-adapter-stack";

function required(app: cdk.App, name: string): string {
  const value = app.node.tryGetContext(name);
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`CDK context '${name}' is required`);
  }
  return value.trim();
}

function booleanValue(app: cdk.App, name: string, fallback: boolean): boolean {
  const value = app.node.tryGetContext(name);
  if (value === undefined) {
    return fallback;
  }
  if (value === true || value === "true") {
    return true;
  }
  if (value === false || value === "false") {
    return false;
  }
  throw new Error(`CDK context '${name}' must be true or false`);
}

const app = new cdk.App();
const harnessArn = required(app, "harnessArn");
const arnParts = harnessArn.split(":");
if (arnParts.length < 6) {
  throw new Error("harnessArn is not a valid ARN");
}

new SlackAdapterStack(app, "__APP_ID__SlackAdapter", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT ?? arnParts[4],
    region: process.env.CDK_DEFAULT_REGION ?? arnParts[3],
  },
  adapterRoot: path.resolve(__dirname, "../../.."),
  appSlug: "__APP_SLUG__",
  harnessArn,
  harnessQualifier: required(app, "harnessQualifier"),
  allowedTeamId: required(app, "allowedTeamId"),
  slackBotUserId: app.node.tryGetContext("slackBotUserId"),
  signingSecretArn: app.node.tryGetContext("signingSecretArn"),
  botTokenSecretArn: app.node.tryGetContext("botTokenSecretArn"),
  sessionHmacSecretArn: app.node.tryGetContext("sessionHmacSecretArn"),
  bundleDependencies: !booleanValue(app, "skipDependencyBundling", false),
});
