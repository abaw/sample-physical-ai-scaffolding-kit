#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { ClusterStack, GpuWorkerConfig } from "../lib/cluster-stack";
import { InfraStack } from "../lib/infra-stack";

const app = new cdk.App();

const clusterName = app.node.tryGetContext("clusterName") ?? "physai-cluster";
const fsxCapacityGiB = app.node.tryGetContext("fsxCapacityGiB") ?? 1200;
const gpuWorkers: GpuWorkerConfig[] = app.node.tryGetContext("gpuWorkers") ?? [
  { name: "gpu-workers", instanceType: "ml.g6e.2xlarge", count: 1 },
];
const cpuWorkerType = app.node.tryGetContext("cpuWorkerType") ?? "ml.m5.2xlarge";
const cpuWorkerCount = app.node.tryGetContext("cpuWorkerCount") ?? 1;

// Compose the data bucket name from CFN pseudo-parameters so both stacks
// resolve to the same value at deploy time without a CDK cross-stack
// reference. Passing a Bucket object (or even bucket.bucketName, which is a
// stack-scoped token) into another stack causes CDK to auto-create a CFN
// export of the bucket's Arn/Ref. That export then locks the bucket against
// in-place updates whenever the consuming stack is deployed — including
// trivial bucket-name template changes.
const dataBucketName = `${clusterName}-data-${cdk.Aws.ACCOUNT_ID}-${cdk.Aws.REGION}`;

const infra = new InfraStack(app, "PhysaiInfraStack", {
  clusterName,
  fsxCapacityGiB,
  dataBucketName,
  terminationProtection: true,
});

new ClusterStack(app, "PhysaiClusterStack", {
  clusterName,
  vpc: infra.vpc,
  privateSubnet: infra.privateSubnet,
  clusterSg: infra.clusterSg,
  dataBucketName,
  fsxFileSystem: infra.fsxFileSystem,
  fsxDnsName: infra.fsxDnsName,
  fsxMountName: infra.fsxMountName,
  dbEndpoint: infra.dbEndpoint,
  dbSecret: infra.dbSecret,
  gpuWorkers,
  cpuWorkerType,
  cpuWorkerCount,
});
